"""Turn the gate-fire CSVs into the numbers the writeup needs.

Produces, from a real sweep:

  * G=1 rate        the primary metric — fraction of tasks clearing every hard gate
  * mean score      when final_score is present
  * round histogram how many tasks needed 0 / 1 / 2 / 3 repair rounds
  * failure table   gate_id x cause_code counts — this is Figure 3
  * token cost      prompt + completion tokens, so the score/cost view is honest

Usage:
    python scripts/report_telemetry.py telemetry/tasks.csv telemetry/gates.csv
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


def read(path: str) -> list[dict]:
    handle = Path(path)
    if not handle.exists():
        raise SystemExit(f"missing {path}")
    with handle.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(tasks_csv: str, gates_csv: str) -> None:
    tasks = read(tasks_csv)
    fired = [row for row in read(gates_csv) if row["passed"] == "0"]

    total = len(tasks)
    cleared = sum(int(row["hard_pass"]) for row in tasks)
    scores = [float(row["final_score"]) for row in tasks if row.get("final_score") not in ("", None)]

    print(f"tasks                     {total}")
    print(f"G=1 rate (hard gates)     {cleared}/{total} = {cleared / total:.3f}")
    if scores:
        print(f"mean score                {sum(scores) / len(scores):.4f}  (n={len(scores)})")

    rounds = Counter(int(row["rounds_used"]) for row in tasks)
    print("rounds used               " + "  ".join(f"{k}:{v}" for k, v in sorted(rounds.items())))

    ptok = sum(int(row["prompt_tokens"] or 0) for row in tasks)
    ctok = sum(int(row["completion_tokens"] or 0) for row in tasks)
    print(f"tokens                    prompt={ptok:,} completion={ctok:,} total={ptok + ctok:,}")
    if total:
        print(f"tokens per task           {(ptok + ctok) / total:,.0f}")

    wall = sum(float(row["wall_seconds"] or 0) for row in tasks)
    print(f"wall time                 {wall / 60:.1f} min total, {wall / max(total, 1):.0f} s/task")

    print("\nfailures by discipline")
    per_disc: dict[str, Counter] = defaultdict(Counter)
    for row in fired:
        per_disc[row["discipline"]][row["cause_code"]] += 1
    for discipline, counter in sorted(per_disc.items()):
        print(f"  {discipline:<12} {dict(counter.most_common())}")

    print("\nfailures by gate (Figure 3)")
    per_gate = Counter(row["gate_id"] for row in fired)
    for gate_id, count in per_gate.most_common():
        print(f"  {gate_id:<24} {count}")

    resolved = Counter(row["round"] for row in fired)
    print("\nfailures by round (where repair bites)")
    for round_index, count in sorted(resolved.items()):
        print(f"  round {round_index}: {count}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
