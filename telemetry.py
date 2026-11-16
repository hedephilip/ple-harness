"""Gate-fire telemetry.

This file exists because of a specific mistake: the evidence for the
writeup (Figure 3, the failure breakdown) cannot be reconstructed after
the fact. It has to be written as the sweep runs, on run 1, including the
run_index — Stage 2 averages three independent runs, so variance is a
scored quantity and a single-run CSV cannot show it.

Two streams:
  gates.csv  one row per gate evaluation, per round
  tasks.csv  one row per task, per run
"""
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Iterable

from verify import GateResult

GATE_FIELDS = [
    "run_id", "run_index", "task_id", "discipline", "round",
    "gate_id", "severity", "passed", "cause_code",
    "observed", "limit", "unit", "signature", "elapsed_ms",
]

TASK_FIELDS = [
    "run_id", "run_index", "task_id", "discipline",
    "hard_pass", "rounds_used", "hard_failures",
    "model_api", "prompt_tokens", "completion_tokens", "wall_seconds",
    "final_score", "error",
]


class Telemetry:
    def __init__(self, directory: str | os.PathLike | None = None,
                 run_index: int = 0, run_id: str | None = None) -> None:
        root = Path(directory or os.environ.get("TELEMETRY_DIR", "telemetry"))
        root.mkdir(parents=True, exist_ok=True)
        self.gates_path = root / "gates.csv"
        self.tasks_path = root / "tasks.csv"
        self.run_index = run_index
        self.run_id = run_id or os.environ.get("RUN_ID") or time.strftime("%Y%m%d-%H%M%S")
        self._ensure(self.gates_path, GATE_FIELDS)
        self._ensure(self.tasks_path, TASK_FIELDS)

    @staticmethod
    def _ensure(path: Path, fields: list[str]) -> None:
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=fields).writeheader()

    def log_gates(self, task_id: str, discipline: str, round_index: int,
                  results: Iterable[GateResult], elapsed_ms: float = 0.0) -> None:
        with self.gates_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=GATE_FIELDS)
            for result in results:
                row = result.to_row()
                writer.writerow({
                    "run_id": self.run_id,
                    "run_index": self.run_index,
                    "task_id": task_id,
                    "discipline": discipline,
                    "round": round_index,
                    "gate_id": row["gate_id"],
                    "severity": row["severity"],
                    "passed": int(row["passed"]),
                    "cause_code": row["cause_code"],
                    "observed": row["observed"],
                    "limit": row["limit"],
                    "unit": row["unit"],
                    "signature": row["signature"],
                    "elapsed_ms": round(elapsed_ms, 2),
                })

    def log_task(self, task_id: str, discipline: str, hard_pass: bool, rounds_used: int,
                 failures: Iterable[GateResult], model_api: str, prompt_tokens: int,
                 completion_tokens: int, wall_seconds: float,
                 final_score: float | None = None, error: str = "") -> None:
        failures = list(failures)
        with self.tasks_path.open("a", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=TASK_FIELDS).writerow({
                "run_id": self.run_id,
                "run_index": self.run_index,
                "task_id": task_id,
                "discipline": discipline,
                "hard_pass": int(hard_pass),
                "rounds_used": rounds_used,
                "hard_failures": json.dumps([r.cause_code for r in failures]),
                "model_api": model_api,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "wall_seconds": round(wall_seconds, 2),
                "final_score": "" if final_score is None else final_score,
                "error": error,
            })

    @staticmethod
    def clearance_rate(tasks_csv: str | os.PathLike) -> float:
        """G=1 rate — the primary metric, straight from the log."""
        path = Path(tasks_csv)
        if not path.exists():
            return 0.0
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return 0.0
        return sum(int(row["hard_pass"]) for row in rows) / len(rows)
