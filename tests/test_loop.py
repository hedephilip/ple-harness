"""End-to-end test of the gated completion loop, without a model or a socket.

Uses a scripted client and an in-memory channel to prove three properties:

  1. `done` is never sent while a hard gate fails.
  2. A failing round produces machine-generated feedback, not prose.
  3. A lesson is admitted only after a mechanically observed fail -> pass.
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
from protocol import ExecResult
from telemetry import Telemetry

UNITS = {f"structural.{key}": unit for key, unit in {
    "Fy_ksi": "ksi", "Zx_in3": "in^3", "Mu_kip_ft": "kip-ft",
    "d_in": "in", "tw_in": "in", "Vu_kip": "kip",
    "L_span_in": "in", "delta_L_in": "in"}.items()}
REVS = [{"doc_id": "S-201", "rank": "IFC", "revision": 1, "value": 11.0}]

BASE = {"Fy_ksi": 50, "Zx_in3": 100, "d_in": 16, "tw_in": 0.4,
        "Vu_kip": 150, "L_span_in": 360, "delta_L_in": 0.8}


REQS = [{"clause": "AISC 360-16 F2", "value": "phi_b = 0.90"},
        {"clause": "AISC 360-16 L3", "value": "L/360 live load"}]


def memo(mu: float) -> str:
    claims = {"units": UNITS,
              "structural": {**BASE, "Mu_kip_ft": mu},
              "requirements": REQS,
              "revisions": REVS}
    return ("# Flexure check\n\n<!-- PLE-CLAIMS\n" + json.dumps(claims) + "\n-->\n")


class FakeChannel:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.done_summary: str | None = None

    async def start(self) -> None: ...
    async def close(self) -> None: ...

    async def read_file(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def read_text(self, path: str) -> str:
        return (await self.read_file(path)).decode()

    async def write_file(self, path: str, data) -> None:
        self.files[path] = data.encode() if isinstance(data, str) else data

    async def exec(self, cmd: str, workdir=None, timeout=None) -> ExecResult:
        return ExecResult("", "", 0)

    async def done(self, summary: str) -> None:
        self.done_summary = summary


class ScriptedClient:
    """Replays a fixed list of completions."""

    model_api = "fake-model"

    def __init__(self, script: list[Completion]) -> None:
        self.script = list(script)
        self.calls = 0

    def complete(self, messages, tools=None, **kwargs) -> Completion:
        self.calls += 1
        if not self.script:
            return Completion(content="exhausted")
        return self.script.pop(0)


def write_call(path: str, content: str, call_id: str = "c1") -> Completion:
    return Completion(
        content="",
        tool_calls=[{
            "id": call_id, "type": "function",
            "function": {"name": "write_file",
                         "arguments": json.dumps({"path": path, "content": content})},
        }],
    )


def stop(text: str = "finished") -> Completion:
    return Completion(content=text)


class TestGatedLoop(unittest.TestCase):
    def _harness(self, script, max_fix_rounds=3):
        self.tmp = tempfile.mkdtemp()
        client = ScriptedClient(script)
        playbook = Playbook(Path(self.tmp) / "playbook.jsonl")
        telemetry = Telemetry(self.tmp, run_index=0, run_id="test")
        return GatedHarness(client, playbook, telemetry, max_fix_rounds=max_fix_rounds), playbook

    def _task(self):
        return {"task_id": "T-001", "prompt": "Size the beam.",
                "discipline": "structural", "deliverables": ["memo.md"]}

    def test_fail_then_repair_then_pass(self):
        bad = memo(400)     # 400 > 375 kip-ft
        good = memo(300)
        harness, playbook = self._harness([
            write_call("memo.md", bad), stop(),      # round 1 -> gate fails
            write_call("memo.md", good), stop(),     # round 2 -> gate passes
        ])
        channel = FakeChannel()
        passed, summary = asyncio.run(harness.run(channel, self._task()))

        self.assertTrue(passed, summary)
        self.assertIn("gated", summary)

        with (Path(self.tmp) / "tasks.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hard_pass"], "1")
        self.assertEqual(rows[0]["rounds_used"], "2")

        with (Path(self.tmp) / "gates.csv").open() as handle:
            gates = list(csv.DictReader(handle))
        self.assertIn("0", {r["passed"] for r in gates})   # a failure was observed
        self.assertIn("1", {r["passed"] for r in gates})   # and then a pass
        self.assertIn("FLEXURE_DCR_EXCEEDED", {r["cause_code"] for r in gates})

    def test_never_passes_with_failure_remaining(self):
        harness, _ = self._harness(
            [write_call("memo.md", memo(500)), stop()] * 4, max_fix_rounds=1)
        channel = FakeChannel()
        passed, summary = asyncio.run(harness.run(channel, self._task()))
        self.assertFalse(passed)
        self.assertIn("unresolved hard-gate failures", summary)
        self.assertIsNone(channel.done_summary)   # `done` is sent by serve.py, not here

    def test_missing_deliverable_blocks(self):
        harness, _ = self._harness([stop("I could not do it")], max_fix_rounds=0)
        channel = FakeChannel()
        passed, summary = asyncio.run(harness.run(channel, self._task()))
        self.assertFalse(passed)
        self.assertIn("MISSING_DELIVERABLE", summary)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
