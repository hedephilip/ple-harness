"""Draw the two result figures the competition requires.

Figure 1 is the dev-set failure breakdown; Figure 3 is score against compute
budget. Both read committed data — `artifacts/manifest.json` for per-task
rewards, `gates.csv` for failure causes, `tasks.csv` for wall time — and refuse
to draw when that data does not exist. An invented figure is worse than a
missing one: the Overview's minimum requirements ask for them, and a plot of
made-up numbers misrepresents the entry.

    python scripts/make_result_figures.py [--artifacts DIR] [--telemetry DIR]

Needs matplotlib, which is a dev-machine dependency, not a container one: it is
deliberately absent from requirements.txt so the submission image stays at one
line.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIGURES = ROOT / "docs" / "figures"

DISCIPLINES = ("structural", "civil", "electrical", "mechanical")


def load_manifest(path: pathlib.Path) -> dict:
    if not path.is_file():
        sys.exit(f"refusing to draw: {path} does not exist.\n"
                 "Run `uv run python eval/run.py` first; an invented figure "
                 "would misrepresent the entry.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    # Provenance guard, added after a test fixture wrote two synthetic plots into
    # docs/figures: eval/run.py stamps harness metadata and a commit, so a
    # hand-made manifest cannot pass for a real run.
    if not isinstance(manifest.get("harness"), dict) or not manifest.get("commit"):
        sys.exit(f"refusing to draw: {path} lacks harness/commit metadata, so it "
                 "was not written by eval/run.py. Figures must come from a real run.")
    return manifest


def tasks_of(manifest: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for task_id, entry in (manifest.get("tasks") or {}).items():
        if isinstance(entry, dict):
            try:
                out[task_id] = float(entry.get("reward", 0.0) or 0.0)
            except (TypeError, ValueError):
                out[task_id] = 0.0
    return out


def discipline_of(task_id: str) -> str:
    lowered = task_id.lower()
    for name in DISCIPLINES:
        if name in lowered:
            return name
    return "other"


def read_csv(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def figure_failures(gates: list[dict], rewards: dict[str, float], out: pathlib.Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    causes = collections.Counter(row.get("cause_code") or "unknown"
                                 for row in gates if str(row.get("passed", "True")) == "False")
    zeros = sum(1 for value in rewards.values() if value == 0.0)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    if causes:
        labels, values = zip(*causes.most_common(8))
        axes[0].barh(range(len(labels)), values, color="#38bdf8")
        axes[0].set_yticks(range(len(labels)))
        axes[0].set_yticklabels(labels, fontsize=8)
        axes[0].invert_yaxis()
        axes[0].set_xlabel("hard failures")
    else:
        axes[0].text(0.5, 0.5, "no gates.csv rows", ha="center", va="center")
        axes[0].set_axis_off()
    axes[0].set_title("Failures by cause code", fontsize=10)

    names = sorted(rewards)
    axes[1].bar(range(len(names)), [rewards[n] for n in names], color="#94a3b8")
    axes[1].set_xticks(range(len(names)))
    axes[1].set_xticklabels([n[:12] for n in names], rotation=90, fontsize=6)
    axes[1].set_ylabel("reward")
    axes[1].set_title(f"Per-task reward ({zeros} of {len(names)} at zero)", fontsize=10)

    fig.suptitle("Figure 1 — dev-set failure breakdown (29 tasks)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def figure_score_cost(rewards: dict[str, float], tasks: list[dict], out: pathlib.Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    minutes: dict[str, float] = {}
    for row in tasks:
        task_id = row.get("task_id") or row.get("task") or ""
        try:
            minutes[task_id] = float(row.get("wall_seconds") or row.get("seconds") or 0) / 60.0
        except (TypeError, ValueError):
            minutes[task_id] = 0.0

    points = [(minutes.get(n, 0.0), rewards[n]) for n in rewards]
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    if points:
        ax.scatter([p[0] for p in points], [p[1] for p in points], color="#38bdf8", s=28)
    mean_score = sum(rewards.values()) / len(rewards) if rewards else 0.0
    mean_minutes = sum(p[0] for p in points) / len(points) if points else 0.0
    if points:
        ax.axhline(mean_score, color="#f8b45a", lw=1, ls="--",
                   label=f"mean score {mean_score:.3f}")
        ax.axvline(mean_minutes, color="#64748b", lw=1, ls=":",
                   label=f"mean {mean_minutes:.1f} min/task")
        ax.legend(fontsize=8)
    ax.set_xlabel("wall-clock minutes per task")
    ax.set_ylabel("reward")
    ax.set_title("Figure 3 — dev-set score against compute budget", fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default=str(ROOT / "artifacts"))
    ap.add_argument("--telemetry", default=str(ROOT / "telemetry"))
    ap.add_argument("--out", default=str(FIGURES))
    args = ap.parse_args()

    artifacts = pathlib.Path(args.artifacts)
    telemetry = pathlib.Path(args.telemetry)
    manifest = load_manifest(artifacts / "manifest.json")
    rewards = tasks_of(manifest)
    if not rewards:
        sys.exit("refusing to draw: manifest.json lists no tasks")

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    figure_failures(read_csv(telemetry / "gates.csv"), rewards,
                    out_dir / "figure1_failures.png")
    figure_score_cost(rewards, read_csv(telemetry / "tasks.csv"),
                      out_dir / "figure3_score_cost.png")

    for name in ("figure1_failures.png", "figure3_score_cost.png"):
        print(f"wrote {out_dir / name}")
    print(f"tasks: {len(rewards)}  mean reward: {sum(rewards.values())/len(rewards):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
