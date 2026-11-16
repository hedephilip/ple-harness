"""The agent loop and its gated completion boundary.

The model proposes. The gate disposes. Nothing in this file allows a task
to end while a hard gate is failing — the only exit from `run()` is either
`all_hard_pass() == True` or an exhausted repair budget, and the second one
is reported as a failure rather than papered over.
"""
from __future__ import annotations

import time
from typing import Any

from gates import assert_registered
from llm import Client, Completion
from playbook import Playbook
from protocol import TaskChannel, deliverables_of, discipline_of
from telemetry import Telemetry
from verify import GATES, GateResult
from gates.cross import claims_of

MAX_STEPS_PER_ROUND = 40

SYSTEM_PROMPT = """You are a licensed-review-grade physical engineering agent.

You work inside a project folder containing drawings, spreadsheets, emails and
superseded revisions. Produce the deliverables the task asks for, at the exact
paths given.

CRITICAL — every deliverable you write MUST contain a machine-readable claims
block containing the raw inputs behind each calculation, so the numbers can be
recomputed independently:

<!-- PLE-CLAIMS
{
  "units": {"<key>": "<unit>", "...": "..."},
  "<discipline>": {"<input>": <number>, "...": <number>},
  "revisions": [{"doc_id": "...", "rank": "AHJ|Addendum|RFI|IFC|Preliminary",
                 "revision": 1, "value": 0.0}]
}
-->

Rules that are checked mechanically and cannot be talked around:
- Every number in the claims block must declare a unit in `units`.
- The same quantity appearing in two deliverables must have the same value.
- Where documents conflict, only the highest-ranked revision governs
  (AHJ > Addendum > RFI > IFC > Preliminary). Cite ranks you actually read.
- Round quantities up. A takeoff of 10.4 cartons is 11 cartons.
- Check the *cumulative* voltage drop, not only each segment.

When you believe the work is complete, stop calling tools and reply with a
short summary. A mechanical gate then re-reads your files from disk. If it
fails, you will be told exactly which check failed with observed and limit
values, and you may repair it.
"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Run a shell command inside the task container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "workdir": {"type": "string"},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the task container. Returns UTF-8 text.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text to a path in the task container, creating parents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
]


class GatedHarness:
    def __init__(self, client: Client, playbook: Playbook, telemetry: Telemetry,
                 max_fix_rounds: int = 3, max_steps: int = MAX_STEPS_PER_ROUND,
                 enforce: bool = True) -> None:
        self.client = client
        self.playbook = playbook
        self.telemetry = telemetry
        self.max_fix_rounds = max_fix_rounds
        self.max_steps = max_steps
        # `enforce=False` is the ablation arm: gates are still evaluated and
        # logged, but never block completion and never trigger a repair round.
        # Without this the gate-on / gate-off comparison cannot be measured.
        self.enforce = enforce
        self.prompt_tokens = 0
        self.completion_tokens = 0

    # -- context ----------------------------------------------------------
    async def _collect(self, channel: TaskChannel, deliverables: list[str],
                       discipline: str) -> dict[str, Any]:
        """Re-read the artifact from disk. The model's claims are not evidence."""
        files: dict[str, bytes] = {}
        for path in deliverables:
            try:
                files[path] = await channel.read_file(path)
            except Exception:
                continue          # absent file -> contract gate reports it
        ctx: dict[str, Any] = {
            "task_type": discipline,
            "deliverables": deliverables,
            "files": files,
            "data": {},
        }
        merged: dict[str, Any] = {}
        for claims in claims_of(ctx).values():
            for key, value in claims.items():
                merged.setdefault(key, value)
        ctx["data"][discipline] = merged.get(discipline, {})
        ctx["data"]["revisions"] = merged.get("revisions", [])
        return ctx

    # -- one agent turn ---------------------------------------------------
    async def _agent_turn(self, channel: TaskChannel,
                          messages: list[dict]) -> Completion:
        for _ in range(self.max_steps):
            completion = self.client.complete(messages, tools=TOOLS)
            self.prompt_tokens += completion.prompt_tokens
            self.completion_tokens += completion.completion_tokens
            messages.append(completion.as_message())
            if not completion.tool_calls:
                return completion
            for call in completion.tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": await self._execute(channel, call),
                })
        return Completion(content="step budget exhausted")

    async def _execute(self, channel: TaskChannel, call: dict) -> str:
        name = (call.get("function") or {}).get("name")
        args = Client.parse_arguments(call)
        try:
            if name == "exec":
                result = await channel.exec(args.get("cmd", ""), args.get("workdir"))
                return f"exit={result.exit_code}\n{result.stdout}\n{result.stderr}"[:6000]
            if name == "read_file":
                return (await channel.read_text(args.get("path", "")))[:20000]
            if name == "write_file":
                await channel.write_file(args.get("path", ""), args.get("content", ""))
                return f"wrote {len(args.get('content', ''))} bytes"
        except Exception as exc:
            return f"tool error: {type(exc).__name__}: {exc}"
        return f"unknown tool {name!r}"

    # -- gated completion -------------------------------------------------
    def _feedback(self, failures: list[GateResult]) -> tuple[str, dict[str, str]]:
        lines = ["MECHANICAL GATE FAILED. The artifacts on disk do not satisfy the "
                 "following checks. Repair them, then stop again.", ""]
        hints: dict[str, str] = {}
        lesson = self.playbook.retrieve_one(failures)
        for result in failures:
            lines.append(f"- {result.feedback()}")
            hints[result.gate_id] = result.detail or result.cause_code
        if lesson is not None:
            result, entry = lesson
            lines.append("")
            lines.append(f"Relevant verified recovery for {result.gate_id}: {entry.hint}")
            hints[result.gate_id] = entry.hint
        return "\n".join(lines), hints

    async def run(self, channel: TaskChannel, task: dict) -> tuple[bool, str]:
        assert_registered()
        discipline = discipline_of(task)
        deliverables = deliverables_of(task)
        task_id = str(task.get("task_id") or task.get("id") or "unknown")
        started = time.time()

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": str(task.get("prompt", ""))},
        ]

        rounds_used = 0
        failures: list[GateResult] = []
        pending_prev: list[GateResult] = []
        artifact_path = deliverables[0] if deliverables else ""
        passed = False

        budget = (self.max_fix_rounds + 1) if self.enforce else 1
        for round_index in range(budget):
            rounds_used = round_index + 1
            completion = await self._agent_turn(channel, messages)

            ctx = await self._collect(channel, deliverables, discipline)
            gate_started = time.time()
            results = GATES.run(discipline, ctx)
            elapsed_ms = (time.time() - gate_started) * 1000
            self.telemetry.log_gates(task_id, discipline, round_index, results, elapsed_ms)

            # Settle last round's pending lessons against a mechanical observation:
            # a lesson is admitted only if the same gate now passes on the same path.
            if pending_prev:
                now_by_gate = {r.gate_id: r for r in results}
                for previous in pending_prev:
                    current = now_by_gate.get(previous.gate_id)
                    self.playbook.admit(previous, artifact_path,
                                        recovered=bool(current and current.passed))
                pending_prev = []

            if GATES.all_hard_pass(results):
                failures = []
                passed = True
                break

            failures = GATES.hard_failures(results)
            if round_index == budget - 1:
                break

            feedback, hints = self._feedback(failures)
            for result in failures:
                self.playbook.note_pending(result, artifact_path,
                                           hints.get(result.gate_id, result.cause_code))
            pending_prev = failures
            messages.append({"role": "user", "content": feedback})

        wall = time.time() - started
        self.telemetry.log_task(
            task_id=task_id, discipline=discipline, hard_pass=passed,
            rounds_used=rounds_used, failures=failures, model_api=self.client.model_api,
            prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens,
            wall_seconds=wall,
            error="" if passed else f"{len(failures)} hard gate(s) unresolved",
        )

        if passed:
            summary = completion.content.strip() or "Deliverables written and verified."
            return True, f"{summary}\n\n[gated] all hard gates passed in {rounds_used} round(s)."
        detail = "; ".join(f"{r.gate_id}:{r.cause_code}" for r in failures)
        return False, (f"Task completed with unresolved hard-gate failures after "
                       f"{rounds_used} round(s): {detail}")

    def _reset_usage(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
