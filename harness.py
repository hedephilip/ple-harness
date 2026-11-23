"""The agent loop and its gated completion boundary.

The model proposes. The gate disposes. The only exits from `run()` are a
verified pass or an exhausted repair budget, and the second is reported as a
failure rather than papered over.
"""
from __future__ import annotations

import asyncio
import shlex
import time
from typing import Any, Callable

from extract import archive_members, text_of
from mcp import McpClient, tool_alias
from gates import assert_registered
from gates.cross import claims_of
from llm import Client, Completion
from playbook import Playbook
from protocol import (ProtocolError, Task, TaskCancelled, TaskChannel,
                      deliverables_of, discipline_of)
from telemetry import Telemetry
from verify import GATES, GateResult

MAX_STEPS_PER_ROUND = 40
# A step budget alone does not stop a discovery loop. The first dev run spent
# 123 of 124 tool calls on `find`/`read_file` and wrote nothing, then ran out
# of steps: the budget was consumed, the deliverable never existed. After this
# many consecutive read-only steps with no write, one reminder is injected
# saying so. It is a nudge, not a second prompt layer — it fires once per
# round and never on its own account of what the deliverable should contain.
READ_ONLY_STREAK_LIMIT = 12
READ_ONLY_NUDGE = (
    "You have used {n} tool calls in a row reading and have written nothing. "
    "Stop reading. Write the deliverable now, at the exact path in the "
    "instruction, including the PLE-CLAIMS block. A partial file that exists "
    "scores; a complete plan that was never written scores zero."
)
# Delivered artifacts are folders and zip packages, not single files: in
# eval/dev_set.yaml 14 dev tasks deliver a folder and 12 a submission.zip, so
# discovery and collection have to walk into both.
MAX_DELIVERABLES = 40
MAX_FILES_PER_DIR = 20

SYSTEM_PROMPT = """You are a licensed-review-grade physical engineering agent.

You work inside a project folder containing drawings, spreadsheets, emails and
superseded revisions. Produce the deliverables the task asks for, at the exact
paths given in the instruction.

CRITICAL — every deliverable you write MUST contain a machine-readable claims
block containing the raw inputs behind each calculation, so the numbers can be
recomputed independently rather than trusted:

<!-- PLE-CLAIMS
{
  "units": {"<discipline>.<key>": "<unit>", "...": "..."},
  "<discipline>": {"<input>": <number>, "...": <number>},
  "requirements": [{"clause": "<code clause>", "value": "<stated limit>"}],
  "revisions": [{"doc_id": "...", "rank": "AHJ|Addendum|RFI|IFC|Preliminary",
                 "revision": 1, "value": 0.0}]
}
-->

Rules that are checked mechanically and cannot be argued around:
- Every number in the claims block must declare a unit in `units`.
- The same quantity in two deliverables must have the same value.
- Where documents conflict, only the highest-ranked revision governs
  (AHJ > Addendum > RFI > IFC > Preliminary). Cite the ranks you actually read.
- List every requirement you applied, with its clause and value. Corpus
  navigation is graded.
- Round quantities up: a takeoff of 10.4 cartons is 11 cartons.
- Check the cumulative voltage drop across a run, not only each segment.

When you believe the work is complete, stop calling tools and reply with a
short summary. A mechanical gate then re-reads your files from disk. If it
fails you will be told exactly which check failed, with observed and limit
values, and you may repair it.
"""

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "exec",
        "description": "Run a bash command inside the task container, in the task workdir.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "timeout_sec": {"type": "number"},
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file from the task container.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write text to a path in the task container, creating parents.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean"},
        }, "required": ["path", "content"]},
    }},
]



class GatedHarness:
    def __init__(self, client: Client, playbook: Playbook, telemetry: Telemetry,
                 max_fix_rounds: int = 3, max_steps: int = MAX_STEPS_PER_ROUND,
                 enforce: bool = True, optimize_descent: bool = True,
                 clock: "Callable[[], float] | None" = None) -> None:
        self.client = client
        # Injectable clock so the time-budget path is testable without waiting.
        self._clock = clock or time.monotonic
        self.playbook = playbook
        self.telemetry = telemetry
        # Per-task state: MCP tool alias -> (client, real tool name), and the
        # tool list actually offered to the model this task.
        self._mcp: dict[str, tuple[McpClient, str]] = {}
        self._tools: list[dict[str, Any]] = list(TOOLS)
        self.max_fix_rounds = max_fix_rounds
        self.max_steps = max_steps
        # enforce=False is the ablation arm: gates are evaluated and logged but
        # never block completion and never trigger a repair round.
        self.enforce = enforce
        self.optimize_descent = optimize_descent
        self.prompt_tokens = 0
        self.completion_tokens = 0

    # -- context ----------------------------------------------------------
    async def _discover(self, channel: TaskChannel, task: Task) -> list[str]:
        """Deliverable paths: what the prompt named, plus what changed on disk.

        The first version returned early on declared paths, and otherwise ran
        `find . -maxdepth 3` from the workdir. Anything under /filesystem was
        invisible, which is where dev-set tasks deliver their submission.zip.
        """
        found: list[str] = list(deliverables_of(task))
        try:
            listing = await channel.exec(
                "find /app /filesystem -type f -newer /tmp/.ple_start "
                "2>/dev/null | grep -v -e '/\\.git/' -e '/\\.cache/' "
                "-e '/node_modules/' | head -400")
            for line in listing.output.splitlines():
                path = line.strip()
                if path and path not in found:
                    found.append(path)
        except TaskCancelled:
            raise
        except Exception:
            pass
        return found[:MAX_DELIVERABLES]

    async def _ingest_file(self, channel: TaskChannel, path: str, present: set[str],
                           files: dict[str, bytes], texts: dict[str, str]) -> None:
        try:
            raw = await channel.read_file(path)
        except TaskCancelled:
            raise
        except Exception:
            return
        if raw is None:
            return
        present.add(path)
        files[path] = raw
        if path.lower().endswith(".zip"):
            for member, text in archive_members(path, raw):
                texts[f"{path}!{member}"] = text
            return
        text = text_of(path, raw)
        if text:
            texts[path] = text

    async def _ingest(self, channel: TaskChannel, path: str, present: set[str],
                      files: dict[str, bytes], texts: dict[str, str]) -> None:
        """One declared or discovered path: file, zip package, or folder."""
        try:
            raw = await channel.read_file(path)
        except TaskCancelled:
            raise
        except Exception:
            raw = None
        if raw is not None:
            present.add(path)
            files[path] = raw
            if path.lower().endswith(".zip"):
                for member, text in archive_members(path, raw):
                    texts[f"{path}!{member}"] = text
                return
            text = text_of(path, raw)
            if text:
                texts[path] = text
            return
        # Not a regular file: read_file refuses directories, so a deliverable
        # written as "/app/files/" is enumerated here instead.
        try:
            listing = await channel.exec(
                f"find {shlex.quote(path)} -type f 2>/dev/null "
                f"| head -{MAX_FILES_PER_DIR}")
        except TaskCancelled:
            raise
        except Exception:
            return
        children = [line.strip() for line in listing.output.splitlines() if line.strip()]
        if children:
            present.add(path)
        for child in children[:MAX_FILES_PER_DIR]:
            await self._ingest_file(channel, child, present, files, texts)

    async def _collect(self, channel: TaskChannel, deliverables: list[str],
                       discipline: str, instruction: str = "") -> dict[str, Any]:
        """Re-read the artifacts from disk. The model's claims are not evidence."""
        present: set[str] = set()
        files: dict[str, bytes] = {}
        texts: dict[str, str] = {}
        for path in deliverables:
            await self._ingest(channel, path, present, files, texts)
        ctx: dict[str, Any] = {
            "task_type": discipline,
            "instruction": instruction,
            "deliverables": deliverables,
            "files": files,
            "texts": texts,
            "present": present,
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
    # -- task app servers --------------------------------------------------
    async def _connect_mcp(self, channel: TaskChannel,
                           task: Task) -> list[dict[str, Any]]:
        """Expose the task's MCP tools to the model.

        A server that fails to initialise is logged and skipped: a broken app
        server must not cost the whole task when the shell still works.
        """
        self._mcp = {}
        specs: list[dict[str, Any]] = []
        for entry in (task.mcp_servers or [])[:4]:
            if not isinstance(entry, dict):
                continue
            server = str(entry.get("name") or "mcp")
            url = str(entry.get("url") or "")
            if not url:
                continue
            client = McpClient(channel, server, url)
            try:
                await client.initialize()
                tools = await client.list_tools()
            except TaskCancelled:
                raise
            except Exception as exc:
                await channel.log(f"[mcp] {server}: unavailable "
                                  f"({type(exc).__name__}: {exc})")
                continue
            added = 0
            for tool in tools:
                alias = tool_alias(server, tool.name)
                if alias in self._mcp:
                    continue
                self._mcp[alias] = (client, tool.name)
                specs.append({"type": "function", "function": {
                    "name": alias,
                    "description": (tool.description or f"{tool.name} on {server}")[:1024],
                    "parameters": tool.schema or {"type": "object", "properties": {}},
                }})
                added += 1
            await channel.log(f"[mcp] {server}: {added} tool(s)")
        return specs

    async def _agent_turn(self, channel: TaskChannel,
                          messages: list[dict]) -> Completion:
        read_streak = 0
        nudged = False
        for _ in range(self.max_steps):
            if channel.cancelled.is_set():
                raise TaskCancelled("time is up")
            # The client is synchronous urllib with a long timeout. Run it off
            # the event loop and race it against `cancel`, otherwise the reader
            # cannot see the cancel frame and `done` misses the ten-second grace
            # protocol.md section 4 allows.
            call = asyncio.create_task(
                asyncio.to_thread(self.client.complete, messages, self._tools))
            cancelled = asyncio.create_task(channel.wait_cancelled())
            try:
                done, _ = await asyncio.wait(
                    {call, cancelled}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                pass
            if cancelled in done:
                call.cancel()
                raise TaskCancelled("time is up")
            cancelled.cancel()
            completion = call.result()
            self.prompt_tokens += completion.prompt_tokens
            self.completion_tokens += completion.completion_tokens
            await channel.usage(self.client.model_name, completion.prompt_tokens,
                                completion.completion_tokens)
            messages.append(completion.as_message())
            if not completion.tool_calls:
                return completion
            for call in completion.tool_calls:
                name = (call.get("function") or {}).get("name")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": await self._execute(channel, call),
                })
                if name == "write_file":
                    read_streak = 0
                elif name in ("read_file", "exec"):
                    read_streak += 1
            if read_streak >= READ_ONLY_STREAK_LIMIT and not nudged:
                nudged = True
                await channel.log(
                    f"[nudge] {read_streak} read-only steps with no write")
                messages.append({"role": "user",
                                 "content": READ_ONLY_NUDGE.format(n=read_streak)})
        return Completion(content="step budget exhausted")

    async def _execute(self, channel: TaskChannel, call: dict) -> str:
        name = (call.get("function") or {}).get("name")
        args = Client.parse_arguments(call)
        if name in self._mcp:
            client, real = self._mcp[name]
            try:
                return await client.call_tool(real, args or {})
            except TaskCancelled:
                raise
            except Exception as exc:
                return f"tool error: {type(exc).__name__}: {exc}"
        try:
            if name == "exec":
                result = await channel.exec(args.get("command", ""),
                                            args.get("timeout_sec"))
                tag = " [truncated]" if result.truncated else ""
                tag += " [timed out]" if result.timed_out else ""
                return f"exit={result.exit_code}{tag}\n{result.output}"[:20000]
            if name == "read_file":
                return (await channel.read_text(args.get("path", "")))[:20000]
            if name == "write_file":
                size = await channel.write_file(args.get("path", ""),
                                                args.get("content", ""),
                                                bool(args.get("append", False)))
                return f"wrote {size} bytes"
        except (TaskCancelled, ProtocolError):
            # A closed channel is not a tool error: retrying into a dead socket
            # would end the task with `done` instead of `error`.
            raise
        except Exception as exc:
            return f"tool error: {type(exc).__name__}: {exc}"
        return f"unknown tool {name!r}"

    # -- gated completion -------------------------------------------------
    def _feedback(self, failures: list[GateResult],
                  discipline: str = "hard") -> tuple[str, dict[str, str]]:
        # Name the discipline that failed. Previously every task was told
        # "MECHANICAL GATE FAILED", including structural and electrical ones,
        # which misdirects the repair it is asking for.
        label = (discipline or "hard").upper()
        lines = [f"{label} GATE FAILED. The artifacts on disk do not satisfy the "
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

    async def run(self, channel: TaskChannel, task: Task) -> tuple[bool, str]:
        assert_registered()
        discipline = discipline_of(task)
        task_id = task.session or "unknown"
        started = time.time()
        # Marker for -newer: only files this run wrote count as deliverables.
        try:
            await channel.exec("touch /tmp/.ple_start")
        except TaskCancelled:
            raise
        except Exception as exc:
            await channel.log(f"[acquire] session marker unavailable: {exc}; "
                              "discovery falls back to prompt paths")

        # The task frame says how long is left. Protocol section 4 gives only ten
        # seconds after `cancel`, which is enough to describe a deliverable and
        # not to write one — so stop early enough to finish.
        budget_sec: float | None = None
        try:
            raw = (task.limits or {}).get("agent_timeout_sec")
            budget_sec = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            budget_sec = None
        reserve_sec = 0.0
        deadline: float | None = None
        if budget_sec and budget_sec > 0:
            reserve_sec = min(600.0, max(120.0, budget_sec * 0.05))
            deadline = self._clock() + budget_sec

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task.instruction},
        ]

        rounds_used = 0
        failures: list[GateResult] = []
        no_gate = False
        ran_out_of_time = False
        plateau = False
        # Signature of the previous round's hard failures, for plateau detection.
        previous_signature: tuple[str, ...] | None = None
        pending_prev: list[GateResult] = []
        deliverables: list[str] = list(deliverables_of(task))
        artifact_path = deliverables[0] if deliverables else ""
        passed = False
        summary = ""
        optimized = False
        checkpoint_ctx: dict[str, Any] = {}
        checkpoint_summary = ""

        self._tools = list(TOOLS) + await self._connect_mcp(channel, task)

        budget = (self.max_fix_rounds + 1) if self.enforce else 1
        try:
            for round_index in range(budget):
                if deadline is not None:
                    remaining = deadline - self._clock()
                    if remaining <= reserve_sec:
                        ran_out_of_time = True
                        await channel.log(
                            f"[budget] {remaining:.0f}s left, reserve "
                            f"{reserve_sec:.0f}s: finalising with what is on disk")
                        break
                rounds_used = round_index + 1
                completion = await self._agent_turn(channel, messages)
                summary = completion.content.strip()

                # Discover AFTER the turn. The gate exists to judge what the
                # agent actually wrote; a listing taken before the agent ran
                # would gate an empty folder and fail every check vacuously.
                discovered = await self._discover(channel, task)
                if discovered:
                    deliverables = discovered
                    artifact_path = deliverables[0]

                ctx = await self._collect(channel, deliverables, discipline,
                                          task.instruction)
                gate_started = time.time()
                results = GATES.run(discipline, ctx)
                self.telemetry.log_gates(task_id, discipline, round_index, results,
                                         (time.time() - gate_started) * 1000)

                if pending_prev:
                    now_by_gate = {r.gate_id: r for r in results}
                    for previous in pending_prev:
                        current = now_by_gate.get(previous.gate_id)
                        self.playbook.admit(previous, artifact_path,
                                            recovered=bool(current and current.passed))
                    pending_prev = []

                if not results:
                    # Every gate declined this task: the gate layer has no
                    # opinion, which is a coverage gap, not a verdict.
                    no_gate = True
                    break

                if GATES.all_hard_pass(results):
                    failures = []
                    passed = True
                    if optimized:
                        if not summary or summary == "exhausted":
                            summary = checkpoint_summary
                        break
                    # Objective descent: if budget remains and we haven't optimized yet,
                    # save a verified compliant checkpoint and prompt the agent to minimize
                    # cost/weight/loss while strictly maintaining compliance.
                    if self.enforce and self.optimize_descent and not optimized and round_index < budget - 1:
                        optimized = True
                        checkpoint_ctx = dict(ctx)
                        checkpoint_summary = summary
                        await channel.log(
                            f"[gated] hard gates passed (G=1) in round {round_index + 1}; "
                            "running objective descent to optimize cost/weight/efficiency")
                        messages.append({
                            "role": "user",
                            "content": (
                                "All hard engineering constraints are verified and satisfied (G=1). "
                                "Now perform an objective descent pass to maximize O': refine sizing, "
                                "section properties, or material takeoff to minimize cost, weight, or "
                                "loss while strictly preserving all hard code constraints and keeping "
                                "the PLE-CLAIMS block updated."
                            ),
                        })
                        continue
                    break

                # If an optimization round broke hard constraints, rollback to the verified
                # compliant checkpoint so G=1 is never forfeited for unverified gains.
                if optimized and not GATES.all_hard_pass(results):
                    await channel.log(
                        "[gated] objective descent broke a hard constraint; rolling back "
                        "to verified compliant checkpoint (G=1)")
                    for path, content in (checkpoint_ctx.get("files") or {}).items():
                        if isinstance(content, bytes):
                            await channel.write_file(path, content.decode("utf-8", "replace"))
                    passed = True
                    failures = []
                    summary = checkpoint_summary
                    break

                failures = GATES.hard_failures(results)

                # If a repair round reproduces the same failures, the next round
                # will reproduce them too: the agent is not making progress, and
                # spending the remaining budget on it only burns tokens. Stop and
                # report, rather than looping until the budget is gone.
                signature = tuple(sorted(f"{r.gate_id}:{r.cause_code}"
                                         for r in failures))
                if signature and signature == previous_signature:
                    await channel.log(
                        "[gated] no progress: the same checks failed again after a "
                        "repair round; stopping instead of repeating it")
                    plateau = True
                    break
                previous_signature = signature

                # Nothing readable on disk means the gate had nothing to judge.
                # Re-prompting "repair the artifacts" would burn whole model
                # rounds on advice the agent cannot act on.
                if not ctx["files"]:
                    break
                if round_index == budget - 1:
                    break

                feedback, hints = self._feedback(failures, discipline)
                for result in failures:
                    self.playbook.note_pending(result, artifact_path,
                                               hints.get(result.gate_id, result.cause_code))
                pending_prev = failures
                messages.append({"role": "user", "content": feedback})
        except TaskCancelled:
            summary = summary or "Time limit reached."
            failures = failures or []
            passed = False

        wall = time.time() - started
        self.telemetry.log_task(
            task_id=task_id, discipline=discipline, hard_pass=passed,
            rounds_used=rounds_used, failures=failures, model_api=self.client.model_api,
            prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens,
            wall_seconds=wall,
            error="" if passed else f"{len(failures)} hard gate(s) unresolved",
        )

        if plateau:
            verdict = (f"[gated] repair plateaued after {rounds_used} round(s): the "
                       f"same hard checks failed twice, so further rounds would "
                       f"repeat the same repair.")
        elif ran_out_of_time:
            verdict = (f"[gated] stopped on the time budget after {rounds_used} "
                       f"round(s); gates were not re-run after the stop.")
        elif passed:
            verdict = f"[gated] all hard gates passed in {rounds_used} round(s)."
        elif no_gate:
            verdict = (f"[gated] no gate applies to discipline {discipline!r}: "
                       "the deliverable was not verified. This is a coverage "
                       "gap, not a failure.")
        elif failures:
            detail = "; ".join(f"{r.gate_id}:{r.cause_code}" for r in failures)
            verdict = (f"[gated] {len(failures)} hard gate(s) unresolved after "
                       f"{rounds_used} round(s): {detail}")
        else:
            verdict = ("[gated] no hard gate was evaluated: no readable "
                       "deliverable on disk.")
        try:
            await channel.log(verdict)
        except Exception:  # a closed socket must not change the outcome
            pass

        # `final_message` is handed to the grader, which reads it alongside the
        # files. It carries the agent's own words only: stamping our internal
        # verdict on it would tell the grader the work failed.
        if summary and failures:
            # The summary goes to the grader. Keeping the model's words is right,
            # but letting a run whose own gates failed read as a clean success is
            # not: name what did not verify, in one line.
            codes = ", ".join(sorted({f"{r.gate_id} ({r.cause_code})"
                                      for r in failures}))
            summary = f"{summary}\n\nUnverified in this run: {codes}."
        if summary:
            return passed, summary
        return passed, ("Deliverables written and verified." if passed
                        else "No deliverable produced.")
