"""Mechanical gate layer — the sole authority for task completion.

Invariants (see docs/GATE_CONTRACT.md):

1. Authority separation — the model never certifies its own output.
2. Re-derivation — a gate recomputes the governing quantity from raw inputs.
   It never trusts a capacity, ratio, or verdict the model wrote down.
3. Strict pass — an empty result set, a timeout, or an exception is a FAIL.
   There is no code path where "no evidence" becomes "passed".
4. Signed failure — every failure carries (gate_id, cause_code, observed,
   limit, unit) so the repair prompt is machine-generated, not prose.

The gate layer has no third-party dependencies and no network access.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

HARD = "hard"
SOFT = "soft"


@dataclass(frozen=True)
class GateResult:
    """One mechanical verdict. Immutable so it cannot be edited downstream."""

    gate_id: str
    passed: bool
    cause_code: str = "OK"
    observed: float | None = None
    limit: float | None = None
    unit: str = ""
    detail: str = ""
    severity: str = HARD

    def overrun_ratio(self) -> float | None:
        if self.observed is None or self.limit in (None, 0):
            return None
        return abs(self.observed) / abs(self.limit)

    def signature(self) -> str:
        """Stable 16-char key for playbook retrieval.

        Deliberately keyed on cause_code first: two failures with the same
        magnitude but different causes must not share a lesson.
        """
        bucket = ""
        ratio = self.overrun_ratio()
        if ratio is not None and ratio > 0:
            bucket = f"{math.floor(math.log10(ratio) * 10) / 10:.1f}"
        raw = f"{self.gate_id}|{self.cause_code}|{bucket}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def to_row(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "severity": self.severity,
            "passed": self.passed,
            "cause_code": self.cause_code,
            "observed": self.observed,
            "limit": self.limit,
            "unit": self.unit,
            "detail": self.detail,
            "signature": self.signature(),
        }

    def feedback(self) -> str:
        """Machine-generated repair line — no model prose involved."""
        if self.passed:
            return f"[{self.gate_id}] PASS"
        bits = [f"[{self.gate_id}] FAIL ({self.cause_code})"]
        if self.observed is not None:
            bits.append(f"observed={self.observed:g}{self.unit}")
        if self.limit is not None:
            bits.append(f"limit={self.limit:g}{self.unit}")
        if self.detail:
            bits.append(self.detail)
        return " ".join(bits)


def ok(gate_id: str, detail: str = "", observed: float | None = None,
       limit: float | None = None, unit: str = "") -> GateResult:
    return GateResult(gate_id=gate_id, passed=True, cause_code="OK", observed=observed,
                      limit=limit, unit=unit, detail=detail)


def fail(gate_id: str, cause_code: str, detail: str, observed: float | None = None,
         limit: float | None = None, unit: str = "", severity: str = HARD) -> GateResult:
    return GateResult(gate_id=gate_id, passed=False, cause_code=cause_code, observed=observed,
                      limit=limit, unit=unit, detail=detail, severity=severity)


class GateRegistry:
    """Discipline gates plus cross-cutting gates that always run."""

    def __init__(self) -> None:
        self._by_type: dict[str, list[Callable]] = {}
        self._cross: list[Callable] = []

    def register(self, task_type: str) -> Callable:
        def deco(fn: Callable) -> Callable:
            self._by_type.setdefault(task_type, []).append(fn)
            return fn
        return deco

    def register_cross(self, fn: Callable) -> Callable:
        self._cross.append(fn)
        return fn

    def gates_for(self, task_type: str) -> list[Callable]:
        return list(self._cross) + list(self._by_type.get(task_type, []))

    def run(self, task_type: str, ctx: dict) -> list[GateResult]:
        results: list[GateResult] = []
        for fn in self.gates_for(task_type):
            name = getattr(fn, "__name__", "unnamed_gate")
            try:
                out = fn(ctx)
            except Exception as exc:  # a broken gate must never pass silently
                results.append(fail(name, "GATE_ERROR", f"{type(exc).__name__}: {exc}"))
                continue
            if out is None:
                results.append(fail(name, "GATE_ERROR", "gate returned no result"))
                continue
            results.extend([out] if isinstance(out, GateResult) else out)
        return results

    @staticmethod
    def all_hard_pass(results: Iterable[GateResult]) -> bool:
        results = list(results)
        if not results:
            return False                      # empty is NOT a pass
        hard = [r for r in results if r.severity == HARD]
        if not hard:
            return False                      # no hard evidence is NOT a pass
        return all(r.passed for r in hard)

    @staticmethod
    def hard_failures(results: Iterable[GateResult]) -> list[GateResult]:
        return [r for r in results if r.severity == HARD and not r.passed]


GATES = GateRegistry()


# --------------------------------------------------------------------------
# Artifact access. Gates read from the artifact map that serve.py builds by
# re-reading files from disk — never from the model's message history.
# --------------------------------------------------------------------------

def artifact_text(ctx: dict, path: str) -> str | None:
    raw = ctx.get("files", {}).get(path)
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw


def require_artifacts(ctx: dict, paths: Iterable[str]) -> list[GateResult]:
    """The deliverable contract: every declared path exists and is non-empty."""
    results = []
    for path in paths:
        raw = ctx.get("files", {}).get(path)
        if raw is None:
            results.append(fail("contract_deliverables", "MISSING_DELIVERABLE",
                                f"{path} was not written", unit=""))
        elif len(raw) == 0:
            results.append(fail("contract_deliverables", "EMPTY_DELIVERABLE",
                                f"{path} exists but is empty", unit=""))
    if not results:
        results.append(ok("contract_deliverables", f"{len(list(paths))} deliverable(s) present"))
    return results
