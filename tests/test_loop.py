"""End-to-end test of the gated loop against the real protocol surface.

Uses a scripted client and an in-memory channel. Proves three properties:

  1. `done` is never sent while a hard gate fails.
  2. A failing round produces machine-generated feedback, not prose.
  3. A lesson is admitted only after a mechanically observed fail -> pass,
     and `usage` frames are emitted so Stage 2 cost accounting works.
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import GatedHarness
from llm import Completion
from playbook import Playbook
from protocol import ExecResult, Task
from telemetry import Telemetry

UNITS = {f"structural.{key}": unit for key, unit in {
    "Fy_ksi": "ksi", "Zx_in3": "in^3", "Mu_kip_ft": "kip-ft",
    "d_in": "in", "tw_in": "in", "Vu_kip": "kip",
    "L_span_in": "in", "delta_L_in": "in"}.items()}
REVS = [{"doc_id": "S-201", "rank": "IFC", "revision": 1, "value": 11.0}]
REQS = [{"clause": "AISC 360-16 F2", "value": "phi_b = 0.90"},
        {"clause": "AISC 360-16 L3", "value": "L/360 live load"}]
BASE = {"Fy_ksi": 50, "Zx_in3": 100, "d_in": 16, "tw_in": 0.4,
        "Vu_kip": 150, "L_span_in": 360, "delta_L_in": 0.8}


def memo(mu: float) -> str:
    claims = {"units": UNITS,
              "structural": {**BASE, "Mu_kip_ft": mu},
              "requirements": REQS,
              "revisions": REVS}
    return ("# Flexure check\n\n<!-- PLE-CLAIMS\n" + json.dumps(claims) + "\n-->\n")


class FakeChannel:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.cancelled = asyncio.Event()
        self.done_summary: str | None = None
        self.usage_frames: list[tuple[int, int]] = []
        self.logs: list[str] = []

    async def start(self) -> None: ...
    async def close(self) -> None: ...

    async def read_file(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def read_text(self, path: str) -> str:
        return (await self.read_file(path)).decode()

    async def write_file(self, path: str, data, append: bool = False) -> int:
        raw = data.encode() if isinstance(data, str) else data
        self.files[path] = self.files.get(path, b"") + raw if append else raw
        return len(raw)

    async def exec(self, command: str, timeout_sec=None) -> ExecResult:
        return ExecResult(output="", exit_code=0)

    async def wait_cancelled(self) -> None:
        """The real channel resolves on a cancel frame; tests never do."""
        await asyncio.Event().wait()

    async def log(self, text: str) -> None:
        self.logs.append(text)

    async def usage(self, model, input_tokens, output_tokens, cache_read_tokens=0):
        self.usage_frames.append((input_tokens, output_tokens))

    async def done(self, final_message: str) -> None:
        self.done_summary = final_message


class ScriptedClient:
    model_api = "fake-model"
    model_name = "fake-model"

    def __init__(self, script: list[Completion]) -> None:
        self.script = list(script)
        self.calls = 0

    def complete(self, messages, tools=None, **kwargs) -> Completion:
        self.calls += 1
        if not self.script:
            return Completion(content="exhausted", prompt_tokens=10, completion_tokens=5)
        return self.script.pop(0)


def write_call(path: str, content: str, call_id: str = "c1") -> Completion:
    return Completion(
        content="", prompt_tokens=100, completion_tokens=50,
        tool_calls=[{
            "id": call_id, "type": "function",
            "function": {"name": "write_file",
                         "arguments": json.dumps({"path": path, "content": content})},
        }],
    )


def stop(text: str = "finished") -> Completion:
    return Completion(content=text, prompt_tokens=50, completion_tokens=20)


def read_call(path: str, call_id: str = "r") -> Completion:
    return Completion(
        content="", prompt_tokens=100, completion_tokens=10,
        tool_calls=[{
            "id": call_id, "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": path})},
        }],
    )


class TestReadLoopGuard(unittest.TestCase):
    """The dev run spent 123 of 124 tool calls reading and wrote nothing.

    A step budget does not stop a discovery loop: it just runs out. The guard
    injects exactly one reminder, because a second one only lengthens the
    context that is already failing to produce a file.
    """

    def test_one_nudge_after_a_read_only_streak(self):
        tmp = tempfile.mkdtemp()
        client = ScriptedClient([read_call("task.md", f"r{i}")
                                 for i in range(20)] + [
            write_call("memo.md", memo(300)), stop()])
        harness = GatedHarness(client, Playbook(Path(tmp) / "playbook.jsonl"),
                               Telemetry(tmp, run_index=0, run_id="nudge"),
                               max_fix_rounds=1)
        channel = FakeChannel()
        task = Task(instruction="Size the beam and write memo.md.",
                    workdir="/app", session="T-002")
        passed, _ = asyncio.run(harness.run(channel, task))

        nudges = [line for line in channel.logs if line.startswith("[nudge]")]
        self.assertEqual(len(nudges), 1, f"expected exactly one nudge, got {channel.logs}")
        self.assertTrue(passed, "the guard must not stop the agent writing afterwards")

    def test_no_nudge_when_the_agent_writes_early(self):
        tmp = tempfile.mkdtemp()
        client = ScriptedClient([write_call("memo.md", memo(300)), stop()])
        harness = GatedHarness(client, Playbook(Path(tmp) / "playbook.jsonl"),
                               Telemetry(tmp, run_index=0, run_id="nowrite"),
                               max_fix_rounds=1)
        channel = FakeChannel()
        task = Task(instruction="Size the beam and write memo.md.",
                    workdir="/app", session="T-003")
        asyncio.run(harness.run(channel, task))
        self.assertFalse([line for line in channel.logs if line.startswith("[nudge]")],
                         "a prompt writer must not be nagged")


class TestGatedLoop(unittest.TestCase):
    def _harness(self, script, max_fix_rounds=3, optimize_descent=False):
        self.tmp = tempfile.mkdtemp()
        client = ScriptedClient(script)
        playbook = Playbook(Path(self.tmp) / "playbook.jsonl")
        telemetry = Telemetry(self.tmp, run_index=0, run_id="test")
        return GatedHarness(client, playbook, telemetry,
                            max_fix_rounds=max_fix_rounds,
                            optimize_descent=optimize_descent), playbook

    def _task(self) -> Task:
        return Task(instruction="Size the beam and write memo.md with the flexure check.",
                    workdir="/app", session="T-001")

    def test_fail_then_repair_then_pass(self):
        harness, _ = self._harness([
            write_call("memo.md", memo(400)), stop(),      # 400 > 375 -> fail
            write_call("memo.md", memo(300)), stop(),      # 300 -> pass
        ])
        channel = FakeChannel()
        passed, summary = asyncio.run(harness.run(channel, self._task()))

        self.assertTrue(passed, summary)
        # final_message belongs to the grader: the agent's words, untouched.
        self.assertTrue(summary.startswith("finished"))
        self.assertTrue(any("all hard gates passed" in line
                            for line in channel.logs),
                        f"gate verdict must reach the log, got {channel.logs}")
        self.assertTrue(channel.usage_frames, "usage frames must be emitted for cost accounting")

        with (Path(self.tmp) / "tasks.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["hard_pass"], "1")
        self.assertEqual(rows[0]["rounds_used"], "2")

        with (Path(self.tmp) / "gates.csv").open() as handle:
            gates = list(csv.DictReader(handle))
        self.assertIn("0", {r["passed"] for r in gates})
        self.assertIn("FLEXURE_DCR_EXCEEDED", {r["cause_code"] for r in gates})

    def test_never_passes_with_failure_remaining(self):
        harness, _ = self._harness(
            [write_call("memo.md", memo(500)), stop()] * 4, max_fix_rounds=1)
        channel = FakeChannel()
        passed, summary = asyncio.run(harness.run(channel, self._task()))
        self.assertFalse(passed)
        self.assertTrue(summary.startswith("finished"))
        self.assertIn("Unverified in this run", summary)
        self.assertTrue(any("plateaued" in line or "hard gate(s) unresolved" in line
                            for line in channel.logs), channel.logs)
        self.assertIsNone(channel.done_summary)   # serve.py sends done, not the harness

    def test_missing_deliverable_blocks(self):
        harness, _ = self._harness([stop("I could not do it")], max_fix_rounds=0)
        channel = FakeChannel()
        passed, summary = asyncio.run(harness.run(channel, self._task()))
        self.assertFalse(passed)
        self.assertTrue(summary.startswith("I could not do it"))
        self.assertIn("Unverified in this run", summary)
        self.assertIn("MISSING_DELIVERABLE", " ".join(channel.logs))

    def test_lesson_admitted_only_on_verified_flip(self):
        harness, playbook = self._harness([
            write_call("memo.md", memo(400)), stop(),
            write_call("memo.md", memo(300)), stop(),
        ])
        asyncio.run(harness.run(FakeChannel(), self._task()))
        summary = playbook.summary()
        self.assertEqual(summary["admitted"], 1)
        self.assertEqual(summary["pending"], 0)

    def test_no_lesson_when_never_recovered(self):
        harness, playbook = self._harness(
            [write_call("memo.md", memo(500)), stop()] * 3, max_fix_rounds=1)
        asyncio.run(harness.run(FakeChannel(), self._task()))
        self.assertEqual(playbook.summary()["admitted"], 0)
        self.assertGreaterEqual(playbook.summary()["rejected"], 1)

    def test_ablation_arm_does_not_repair(self):
        """PLE_GATE_MODE=off: gates evaluate and log, but never block or repair."""
        harness, _ = self._harness([write_call("memo.md", memo(500)), stop()])
        harness.enforce = False
        channel = FakeChannel()
        passed, _ = asyncio.run(harness.run(channel, self._task()))
        self.assertFalse(passed)                       # the truth is still recorded
        self.assertEqual(len(channel.usage_frames), 2)  # one agent turn, no repair


class FakeClock:
    """Monotonic stand-in: returns each value in turn, then repeats the last."""

    def __init__(self, values: list[float]) -> None:
        self.values = list(values)

    def __call__(self) -> float:
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class TestTimeBudget(unittest.TestCase):
    def test_stops_before_the_reserve_is_spent(self):
        """A failing task must not repair itself past the deadline.

        Protocol section 4 leaves ten seconds after `cancel`, which is enough to
        describe a deliverable and not enough to write one. With a 3600 s budget
        the reserve is 180 s, so a run that has 100 s left must stop repairing.
        """
        tmp = tempfile.mkdtemp()
        client = ScriptedClient([write_call("memo.md", memo(400)), stop()])
        harness = GatedHarness(
            client, Playbook(Path(tmp) / "playbook.jsonl"),
            Telemetry(tmp, run_index=0, run_id="budget"),
            max_fix_rounds=3, clock=FakeClock([0.0, 0.0, 3500.0, 3500.0]))
        channel = FakeChannel()
        task = Task(instruction="Size the beam and write memo.md with the flexure check.",
                    workdir="/app", session="T-BUDGET",
                    limits={"agent_timeout_sec": 3600})

        passed, summary = asyncio.run(harness.run(channel, task))

        self.assertFalse(passed)
        self.assertEqual(client.calls, 2, "a repair round ran past the reserve")
        self.assertTrue(any("[budget]" in line for line in channel.logs), channel.logs)
        self.assertTrue(any("time budget" in line for line in channel.logs), channel.logs)

    def test_untimed_task_is_unaffected(self):
        tmp = tempfile.mkdtemp()
        client = ScriptedClient([write_call("memo.md", memo(300)), stop()])
        harness = GatedHarness(client, Playbook(Path(tmp) / "playbook.jsonl"),
                               Telemetry(tmp, run_index=0, run_id="untimed"),
                               max_fix_rounds=3, clock=FakeClock([0.0, 10_000.0]))
        channel = FakeChannel()
        task = Task(instruction="Size the beam and write memo.md with the flexure check.",
                    workdir="/app", session="T-UNTIMED")

        passed, _ = asyncio.run(harness.run(channel, task))
        self.assertTrue(passed, "an untimed task must not be cut short")


def memo_with(**overrides) -> str:
    """A claims memo with one structural input overridden."""
    claims = {"units": UNITS,
              "structural": {**BASE, **overrides},
              "requirements": REQS,
              "revisions": REVS}
    return "# Check\n\n<!-- PLE-CLAIMS\n" + json.dumps(claims) + "\n-->\n"


class TestRepairPlateau(unittest.TestCase):
    def test_a_changing_failure_set_is_not_cut_short(self):
        """Plateau detection must fire on staleness, not on any second failure.

        Round 1 fails flexure; round 2 fails shear instead. The failure set
        changed, so the loop must keep repairing rather than stop.
        """
        tmp = tempfile.mkdtemp()
        client = ScriptedClient([
            write_call("memo.md", memo(400)),                    # flexure fails
            stop(),
            write_call("memo.md", memo_with(Vu_kip=300)),         # shear fails
            stop(),
            write_call("memo.md", memo(300)),                    # both pass
            stop(),
        ])
        harness = GatedHarness(client, Playbook(Path(tmp) / "playbook.jsonl"),
                               Telemetry(tmp, run_index=0, run_id="plateau"),
                               max_fix_rounds=3)
        channel = FakeChannel()
        task = Task(instruction="Size the beam and write memo.md with the flexure check.",
                    workdir="/app", session="T-PLATEAU")

        passed, _ = asyncio.run(harness.run(channel, task))

        self.assertTrue(passed, "a changing failure set should still be repairable")
        self.assertFalse(any("no progress" in line for line in channel.logs), channel.logs)


class TestObjectiveDescent(unittest.TestCase):
    """Once hard gates clear (G=1), the harness allocates remaining budget to optimize O'.

    If the optimization pass preserves hard constraints, the optimized deliverable
    is kept. If an over-aggressive optimization violates a hard gate, the harness
    automatically rolls back to the compliant checkpoint so G=1 is never lost.
    """

    def test_objective_descent_preserves_improved_deliverable(self):
        tmp = tempfile.mkdtemp()
        client = ScriptedClient([
            write_call("memo.md", memo(350)), stop("compliant"),    # round 1: G=1 passes
            write_call("memo.md", memo(250)), stop("optimized"),    # round 2: O' optimized & passes
        ])
        harness = GatedHarness(client, Playbook(Path(tmp) / "playbook.jsonl"),
                               Telemetry(tmp, run_index=0, run_id="opt-pass"),
                               max_fix_rounds=3)
        channel = FakeChannel()
        task = Task(instruction="Size the beam and write memo.md with the flexure check.",
                    workdir="/app", session="T-OPT-PASS")

        passed, summary = asyncio.run(harness.run(channel, task))
        self.assertTrue(passed)
        self.assertEqual(summary, "optimized")
        self.assertTrue(any("objective descent" in line for line in channel.logs))
        self.assertIn("250", channel.files["memo.md"].decode())

    def test_objective_descent_rolls_back_if_constraint_broken(self):
        tmp = tempfile.mkdtemp()
        client = ScriptedClient([
            write_call("memo.md", memo(300)), stop("compliant"),    # round 1: G=1 passes (300 <= 375)
            write_call("memo.md", memo(420)), stop("broken"),       # round 2: over-optimized, fails flexure (420 > 375)
        ])
        harness = GatedHarness(client, Playbook(Path(tmp) / "playbook.jsonl"),
                               Telemetry(tmp, run_index=0, run_id="opt-fail"),
                               max_fix_rounds=3)
        channel = FakeChannel()
        task = Task(instruction="Size the beam and write memo.md with the flexure check.",
                    workdir="/app", session="T-OPT-FAIL")

        passed, summary = asyncio.run(harness.run(channel, task))
        self.assertTrue(passed, "must protect G=1 by falling back to compliant checkpoint")
        self.assertEqual(summary, "compliant")
        self.assertTrue(any("rolling back" in line for line in channel.logs))
        self.assertIn("300", channel.files["memo.md"].decode(), "channel file must be restored to compliant state")


if __name__ == "__main__":
    unittest.main(verbosity=2)
