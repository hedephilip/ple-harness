"""Gate fidelity: does our verdict agree with the official grader?

This is the experiment the whole approach stands or falls on. If our gate
says PASS and the official grader awards zero, the gate is not a feasibility
oracle — and any cost descent built on it will confidently walk into
infeasible designs.

Input: two CSVs, joined on task_id.

  our verdicts    gate_verdicts.csv   task_id,hard_pass
  official        grader_scores.csv   task_id,score

The grader CSV normally comes from `uv run python eval/run.py --artifacts`
which grades committed artifacts the way the evaluator does.

Output: the 2x2 confusion matrix plus the four rates that matter.

    python scripts/gate_fidelity.py gate_verdicts.csv grader_scores.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path


def read(path: str) -> dict[str, float]:
    handle = Path(path)
    if not handle.exists():
        raise SystemExit(f"missing {path}")
    rows: dict[str, float] = {}
    with handle.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            task_id = row.get("task_id") or row.get("id")
            if not task_id:
                continue
            value = row.get("hard_pass", row.get("score", 0))
            rows[str(task_id)] = float(value)
    return rows


def main(verdict_csv: str, grader_csv: str, threshold: float = 1e-9) -> None:
    ours = read(verdict_csv)
    official = read(grader_csv)
    joined = sorted(set(ours) & set(official))
    if not joined:
        raise SystemExit("no overlapping task_ids between the two files")

    tp = tn = fp = fn = 0
    for task_id in joined:
        we_pass = ours[task_id] > 0.5
        they_pass = official[task_id] > threshold
        if we_pass and they_pass:
            tp += 1
        elif we_pass and not they_pass:
            fp += 1
        elif not we_pass and they_pass:
            fn += 1
        else:
            tn += 1

    n = len(joined)
    print(f"tasks compared            {n}  (ours={len(ours)}, official={len(official)})")
    print()
    print("                        grader > 0    grader = 0")
    print(f"  gate PASS             {tp:>10}    {fp:>10}")
    print(f"  gate FAIL             {fn:>10}    {tn:>10}")
    print()
    print(f"true positive rate        {tp / n:.3f}   (we kept a real pass)")
    print(f"false positive rate       {fp / n:.3f}   <-- must be ~0 before any cost descent")
    print(f"false negative rate       {fn / n:.3f}   (we discarded real points)")
    print(f"true negative rate        {tn / n:.3f}")
    print(f"agreement                 {(tp + tn) / n:.3f}")

    if fp:
        print(f"\nSTOP: {fp} task(s) pass our gate but score zero officially.")
        print("The gate is not safe as a feasibility oracle. Fix calibration before")
        print("building any O' descent on top of it.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
