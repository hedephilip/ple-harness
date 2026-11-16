"""Conditional failure memory.

Failure knowledge is *conditional* knowledge. Kept in context it misfires,
because the agent applies a lesson to a failure it does not fit. So:

  - lessons live on disk, never in the agent's context;
  - retrieval happens only when a specific signature fires;
  - at most one lesson is injected per repair round;
  - admission requires the same gate to flip fail -> pass on the same
    artifact path, in the next round. Self-reported recovery is not enough.

The full playbook is never serialised into a prompt.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from verify import GateResult


@dataclass
class Lesson:
    signature: str
    gate_id: str
    cause_code: str
    hint: str
    verified: bool
    uses: int = 0

    def render(self) -> str:
        return f"[lesson {self.signature}] {self.gate_id}/{self.cause_code}: {self.hint}"


class Playbook:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path or os.environ.get("PLAYBOOK_PATH", "/tmp/playbook.jsonl"))
        self._lessons: dict[str, Lesson] = {}
        self._pending: dict[tuple[str, str], Lesson] = {}
        self.admitted = 0
        self.rejected = 0
        self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                lesson = Lesson(**record)
            except (json.JSONDecodeError, TypeError):
                continue
            if lesson.verified:
                self._lessons[lesson.signature] = lesson

    def _append(self, lesson: Lesson) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(lesson), ensure_ascii=False) + "\n")

    # -- retrieval --------------------------------------------------------
    def retrieve(self, result: GateResult) -> Lesson | None:
        """The only path by which failure knowledge reaches the agent."""
        if result.passed:
            return None
        lesson = self._lessons.get(result.signature())
        if lesson is None:
            return None
        lesson.uses += 1
        return lesson

    def retrieve_one(self, results: Iterable[GateResult]) -> tuple[GateResult, Lesson] | None:
        """Highest-value single lesson: the worst overrun among hard failures."""
        candidates = []
        for result in results:
            if result.passed or result.severity != "hard":
                continue
            lesson = self.retrieve(result)
            if lesson is not None:
                ratio = result.overrun_ratio() or 0.0
                candidates.append((ratio, result, lesson))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, result, lesson = candidates[0]
        return result, lesson

    # -- admission --------------------------------------------------------
    def note_pending(self, result: GateResult, artifact_path: str, hint: str) -> None:
        """Record what we are about to suggest, so we can verify it later."""
        if result.passed:
            return
        self._pending[(result.signature(), artifact_path)] = Lesson(
            signature=result.signature(),
            gate_id=result.gate_id,
            cause_code=result.cause_code,
            hint=hint,
            verified=False,
        )

    def admit(self, result: GateResult, artifact_path: str, recovered: bool) -> bool:
        """Store a lesson only if a *mechanically observed* flip occurred."""
        key = (result.signature(), artifact_path)
        pending = self._pending.pop(key, None)
        if pending is None:
            self.rejected += 1
            return False
        if not recovered:
            self.rejected += 1
            return False
        admitted = Lesson(signature=pending.signature, gate_id=pending.gate_id,
                          cause_code=pending.cause_code, hint=pending.hint, verified=True)
        self._lessons[admitted.signature] = admitted
        self._append(admitted)
        self.admitted += 1
        return True

    # -- introspection ----------------------------------------------------
    def summary(self) -> dict[str, int]:
        return {"lessons": len(self._lessons), "admitted": self.admitted,
                "rejected": self.rejected, "pending": len(self._pending)}
