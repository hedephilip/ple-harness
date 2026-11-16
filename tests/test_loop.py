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


class TestGatedLoop(unittest.TestCase):
    def _harness(self, script, max_fix_rounds=3):
        self.tmp = tempfile.mkdtemp()
        client = ScriptedClient(script)
        playbook = Playbook(Path(self.tmp) / "playbook.jsonl")
        telemetry = Telemetry(self.tmp, run_index=0, run_id="test")
        return GatedHarness(client, playbook, telemetry,
                            max_fix_rounds=max_fix_rounds), playbook

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
        self.assertIn("gated", summary)
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
        self.assertIn("unresolved hard-gate failures", summary)
        self.assertIsNone(channel.done_summary)   # serve.py sends done, not the harness

    def test_missing_deliverable_blocks(self):
        harness, _ = self._harness([stop("I could not do it")], max_fix_rounds=0)
        passed, summary = asyncio.run(harness.run(FakeChannel(), self._task()))
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

    def test_ablation_arm_does_not_repair(self):
        """PLE_GATE_MODE=off: gates evaluate and log, but never block or repair."""
        harness, _ = self._harness([write_call("memo.md", memo(500)), stop()])
        harness.enforce = False
        channel = FakeChannel()
        passed, _ = asyncio.run(harness.run(channel, self._task()))
        self.assertFalse(passed)                       # the truth is still recorded
        self.assertEqual(len(channel.usage_frames), 2)  # one agent turn, no repair


if __name__ == "__main__":
    unittest.main(verbosity=2)
