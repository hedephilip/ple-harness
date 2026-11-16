"""Cross-cutting gates — run for every task type, before any discipline gate.

These exist because the benchmark's own failure taxonomy is dominated by
bookkeeping, not physics: dropped unit conversions, superseded revisions
shipped as current, and the same quantity stated twice with two values.
A discipline gate cannot see any of that.

Claims block
------------
A deliverable declares its inputs in a machine-readable block so the gate
layer can recompute rather than trust:

    <!-- PLE-CLAIMS
    {
      "units": {"flexure.Fy_ksi": "ksi", "flexure.Zx_in3": "in^3"},
      "flexure": {"Fy_ksi": 50, "Zx_in3": 100, "Mu_kip_ft": 300}
    }
    -->

The units block is mandatory. A claim without a declared unit is a hard
failure, because "300" is not a demand, it is a number.
"""
from __future__ import annotations

import json
import re
from typing import Any

from verify import GATES, GateResult, fail, ok, require_artifacts

CLAIMS_RE = re.compile(r"<!--\s*PLE-CLAIMS\s*(\{.*?\})\s*-->", re.S)

# Revision authority, strongest first. A lower-ranked document never governs.
REVISION_RANK = {"AHJ": 5, "Addendum": 4, "RFI": 3, "IFC": 2, "Preliminary": 1}


def extract_claims(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    matches = CLAIMS_RE.findall(text)
    if not matches:
        return None
    merged: dict[str, Any] = {}
    for blob in matches:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            for key, value in data.items():
                if key in merged and merged[key] != value:
                    # Two blocks disagree; keep both under a suffixed key so the
                    # numeric_agreement gate can surface it rather than hide it.
                    merged[f"{key}#dup"] = value
                else:
                    merged[key] = value
    return merged or None


def flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.update(flatten(value, f"{prefix}[{index}]"))
    else:
        out[prefix] = node
    return out


def claims_of(ctx: dict) -> dict[str, dict[str, Any]]:
    """Per-deliverable claims, keyed by artifact path."""
    found: dict[str, dict[str, Any]] = {}
    for path, raw in ctx.get("files", {}).items():
        if not path.endswith((".md", ".txt")):
            continue
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        claims = extract_claims(text)
        if claims:
            found[path] = claims
    return found


@GATES.register_cross
def contract_deliverables(ctx: dict) -> list[GateResult]:
    """Every declared path exists and is non-empty.

    A task that declares no deliverables is not a pass — it is an
    unverifiable claim, and unverifiable is a failure.
    """
    declared = ctx.get("deliverables") or []
    if not declared:
        return [fail("contract_deliverables", "NO_DELIVERABLES_DECLARED",
                     "the task declared no deliverable paths; nothing can be verified")]
    return require_artifacts(ctx, declared)


@GATES.register_cross
def claims_present(ctx: dict) -> list[GateResult]:
    deliverables = ctx.get("deliverables", [])
    found = claims_of(ctx)
    results: list[GateResult] = []
    for path in deliverables:
        if path not in found:
            results.append(fail(
                "claims_present", "NO_CLAIMS_BLOCK",
                f"{path} has no PLE-CLAIMS block; the gate layer has nothing to recompute",
            ))
    if not results:
        results.append(ok("claims_present", f"{len(found)} claims block(s) parsed"))
    return results


@GATES.register_cross
def unit_declarations(ctx: dict) -> list[GateResult]:
    results: list[GateResult] = []
    for path, claims in claims_of(ctx).items():
        units = claims.get("units")
        if not isinstance(units, dict):
            results.append(fail("unit_declarations", "UNIT_BLOCK_MISSING",
                                f"{path} declares no units map"))
            continue
        declared = set(units)
        for key, value in flatten({k: v for k, v in claims.items()
                                   if k not in ("units", "revisions", "requirements")}).items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if key not in declared:
                results.append(fail("unit_declarations", "UNIT_MISSING",
                                    f"{path}: '{key}' is a bare number with no declared unit",
                                    observed=float(value)))
    if not results:
        results.append(ok("unit_declarations"))
    return results


@GATES.register_cross
def numeric_agreement(ctx: dict, rel_tol: float = 1e-6) -> list[GateResult]:
    """The same quantity, named the same way in two deliverables, must match."""
    seen: dict[str, tuple[str, float]] = {}
    conflicts: list[GateResult] = []
    for path, claims in claims_of(ctx).items():
        for key, value in flatten({k: v for k, v in claims.items()
                                   if k not in ("units", "revisions", "requirements")}).items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if key not in seen:
                seen[key] = (path, float(value))
                continue
            first_path, first_value = seen[key]
            denom = max(abs(first_value), abs(float(value)), 1e-12)
            if abs(first_value - float(value)) / denom > rel_tol:
                conflicts.append(fail(
                    "numeric_agreement", "NUMERIC_CONFLICT",
                    f"'{key}' is {first_value:g} in {first_path} but {float(value):g} in {path}",
                    observed=float(value), limit=first_value,
                ))
    if not conflicts:
        conflicts.append(ok("numeric_agreement", f"{len(seen)} quantity key(s) consistent"))
    return conflicts


@GATES.register_cross
def requirements_listed(ctx: dict) -> list[GateResult]:
    """Corpus navigation is scored.

    PLE paper §3.2: "the solver must also explicitly list the requirements it
    applied, each with clause and value from the associated grounding document.
    The grader checks the listed requirements against the references, so
    successful navigation of the corpus becomes a metric in the final grading."

    Most harnesses treat citation as documentation. It is graded output.
    """
    results: list[GateResult] = []
    for path, claims in claims_of(ctx).items():
        entries = claims.get("requirements")
        if not isinstance(entries, list) or not entries:
            results.append(fail(
                "requirements_listed", "REQUIREMENTS_MISSING",
                f"{path} lists no applied requirements; corpus navigation is graded",
            ))
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                results.append(fail("requirements_listed", "REQUIREMENT_MALFORMED",
                                    f"{path} requirements[{index}] is not an object"))
                continue
            if not str(entry.get("clause") or "").strip():
                results.append(fail("requirements_listed", "REQUIREMENT_NO_CLAUSE",
                                    f"{path} requirements[{index}] cites no clause"))
            if entry.get("value") in (None, ""):
                results.append(fail("requirements_listed", "REQUIREMENT_NO_VALUE",
                                    f"{path} requirements[{index}] states no value"))
    if not results:
        results.append(ok("requirements_listed"))
    return results


@GATES.register_cross
def revision_authority(ctx: dict) -> list[GateResult]:
    """A superseded document must never supply a governing value.

    ctx['data']['revisions'] = [
        {"doc_id": "S-201", "rank": "Addendum", "revision": 2, "value": 12.5},
        {"doc_id": "S-201", "rank": "IFC",      "revision": 1, "value": 11.0},
    ]
    """
    rows = (ctx.get("data") or {}).get("revisions") or []
    if not rows:
        return [fail("revision_authority", "REVISION_TABLE_MISSING",
                     "no revision table supplied; governing revision cannot be established")]
    by_doc: dict[str, list[dict]] = {}
    for row in rows:
        by_doc.setdefault(str(row.get("doc_id")), []).append(row)

    results: list[GateResult] = []
    for doc_id, docs in by_doc.items():
        ranked = sorted(docs, key=lambda r: REVISION_RANK.get(str(r.get("rank")), 0), reverse=True)
        top_rank = REVISION_RANK.get(str(ranked[0].get("rank")), 0)
        tied = [d for d in ranked if REVISION_RANK.get(str(d.get("rank")), 0) == top_rank]
        values = {round(float(d.get("value", 0.0)), 9) for d in tied}
        if len(values) > 1:
            results.append(fail(
                "revision_authority", "REVISION_CONFLICT",
                f"{doc_id}: {len(tied)} documents share rank '{ranked[0].get('rank')}' "
                f"with different values {sorted(values)}; no governing value",
            ))
    if not results:
        results.append(ok("revision_authority", f"{len(by_doc)} document(s) resolved"))
    return results

