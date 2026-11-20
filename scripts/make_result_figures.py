"""Draw the two result figures the competition requires.

Figure 1 is the dev-set failure breakdown; Figure 3 is score against compute
budget. Both read committed data only, and refuse to draw when that data does
not exist. An invented figure is worse than a missing one: the Overview's
minimum requirements ask for these, and a plot of made-up numbers misrepresents
the entry.

Where the data comes from, in preference order:

  causes   `gates.csv` if a local run kept telemetry, otherwise the
           `Unverified in this run: gate (CAUSE), ...` line that a failing run
           appends to its own `final_message.md`. Both are written by the run
           itself, so the cause codes in the figure are the ones the gates
           actually fired, not a taxonomy typed by hand.
  cost     `tasks.csv` (wall seconds) if present, otherwise `trajectory.json`
           per task, which carries `final_metrics.total_prompt_tokens` and
           `total_completion_tokens`. Tokens are the honest cost axis for a
           hosted model: wall time depends on the runner, tokens do not.
  reward   `manifest.json`.

Usage:

    python scripts/make_result_figures.py [--artifacts DIR] [--telemetry DIR] [--out DIR]

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
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIGURES = ROOT / "docs" / "figures"

DISCIPLINES = ("structural", "civil", "electrical", "mechanical")

# "Unverified in this run: claims_present (NO_CLAIMS_BLOCK), flexure (MISSING_INPUT)"
_UNVERIFIED = re.compile(r"Unverified in this run:\s*(.+)", re.S)
_PAIR = re.compile(r"([A-Za-z0-9_\-]+)\s*\(([A-Z0-9_]+)\)")


def provenance_problems(manifest: dict) -> list[str]:
    """List why a manifest cannot be trusted as a real `eval/run.py` output.

    Provenance guard, added after a test fixture wrote two synthetic plots into
    docs/figures. `eval/run.py` writes `format`, a `dev_set` hash and a
    `harness` block carrying the tree hash and the commit, so a hand-made
    fixture cannot pass for a real run.

    The commit is read from `harness.commit` first: that is where the real
    writer puts it. A top-level `commit` is accepted as a fallback for older
    or hand-migrated artifacts, but `harness` plus `format`/`dev_set` stay
    mandatory so the fallback cannot resurrect the fixture hole.
    """
    problems: list[str] = []
    harness = manifest.get("harness")
    if not isinstance(harness, dict):
        problems.append("no `harness` block")
        harness = {}
    if not manifest.get("format"):
        problems.append("no `format` version")
    if not manifest.get("dev_set"):
        problems.append("no `dev_set` hash")
    if not (harness.get("commit") or manifest.get("commit")):
        problems.append("no commit in `harness.commit`")
    if not (harness.get("tree") or harness.get("model_api")):
        problems.append("no harness `tree`/`model_api`")
    return problems


def load_manifest(path: pathlib.Path) -> dict:
    if not path.is_file():
        sys.exit(f"refusing to draw: {path} does not exist.\n"
                 "Run `uv run python eval/run.py` first; an invented figure "
                 "would misrepresent the entry.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems = provenance_problems(manifest)
    if problems:
        sys.exit(f"refusing to draw: {path} was not written by eval/run.py "
                 f"({'; '.join(problems)}). Figures must come from a real run.")
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


def causes_from_gates(gates: list[dict]) -> collections.Counter:
    return collections.Counter(
        row.get("cause_code") or "unknown"
        for row in gates if str(row.get("passed", "True")) == "False")


def causes_from_final_messages(artifacts: pathlib.Path,
                               rewards: dict[str, float]) -> collections.Counter:
    """Read the cause codes a run recorded in its own committed deliverables.

    A failing run appends one line naming every gate it could not verify, so
    the committed artifacts already carry the failure taxonomy. This is the
    same evidence a judge would open, which is what makes it usable here.
    """
    causes: collections.Counter = collections.Counter()
    for task_id in rewards:
        message = artifacts / task_id / "final_message.md"
        if not message.is_file():
            continue
        text = message.read_text(encoding="utf-8", errors="replace")
        match = _UNVERIFIED.search(text)
        if not match:
            continue
        for gate_id, cause in _PAIR.findall(match.group(1)):
            causes[cause] += 1
    return causes


def costs_from_trajectories(artifacts: pathlib.Path,
                            rewards: dict[str, float]) -> dict[str, float]:
    """Token cost per task, read from the trajectory the run committed."""
    out: dict[str, float] = {}
    for task_id in rewards:
        path = artifacts / task_id / "trajectory.json"
        if not path.is_file():
            continue
        try:
            trajectory = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        metrics = trajectory.get("final_metrics") or {}
        total = (float(metrics.get("total_prompt_tokens") or 0)
                 + float(metrics.get("total_completion_tokens") or 0))
        if total:
            out[task_id] = total
    return out


def figure_failures(causes: collections.Counter, rewards: dict[str, float],
                    out: pathlib.Path, source: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

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
        axes[0].text(0.5, 0.5, f"no cause codes in {source}",
                     ha="center", va="center", fontsize=9)
        axes[0].set_axis_off()
    axes[0].set_title("Failures by cause code", fontsize=10)
    axes[0].text(0.99, 0.02, f"source: {source}", transform=axes[0].transAxes,
                 ha="right", fontsize=6, color="#64748b")

    names = sorted(rewards)
    axes[1].bar(range(len(names)), [rewards[n] for n in names], color="#94a3b8")
    axes[1].set_xticks(range(len(names)))
    axes[1].set_xticklabels([n[:12] for n in names], rotation=90, fontsize=6)
    axes[1].set_ylabel("reward")
    axes[1].set_ylim(0, 1.0)
    axes[1].set_title(f"Per-task reward ({zeros} of {len(names)} at zero)", fontsize=10)

    fig.suptitle(f"Figure 1 — dev-set failure breakdown ({len(names)} task(s))",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def figure_score_cost(costs: dict[str, float], rewards: dict[str, float],
                      out: pathlib.Path, unit: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = [(costs.get(n, 0.0), rewards[n]) for n in rewards]
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    if points:
        ax.scatter([p[0] for p in points], [p[1] for p in points],
                   color="#38bdf8", s=28)
    mean_score = sum(rewards.values()) / len(rewards) if rewards else 0.0
    mean_cost = sum(p[0] for p in points) / len(points) if points else 0.0
    if points:
        ax.axhline(mean_score, color="#f8b45a", lw=1, ls="--",
                   label=f"mean score {mean_score:.3f}")
        ax.axvline(mean_cost, color="#64748b", lw=1, ls=":",
                   label=f"mean {mean_cost:,.0f} {unit}")
        ax.legend(fontsize=8)
    ax.set_xlabel(f"model tokens per task ({unit})")
    ax.set_ylabel("reward")
    ax.set_ylim(-0.05, 1.05)
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

    causes = causes_from_gates(read_csv(telemetry / "gates.csv"))
    source = "gates.csv"
    if not causes:
        causes = causes_from_final_messages(artifacts, rewards)
        source = "artifacts/*/final_message.md"
    if not causes:
        sys.exit("refusing to draw: no gate cause codes in gates.csv or in the "
                 "committed final_message files, so there is nothing to plot. "
                 "Figure 1 must show failures the gates actually recorded.")

    costs = {}
    unit = "tokens"
    for row in read_csv(telemetry / "tasks.csv"):
        task_id = row.get("task_id") or row.get("task") or ""
        try:
            costs[task_id] = float(row.get("wall_seconds") or row.get("seconds") or 0)
        except (TypeError, ValueError):
            costs[task_id] = 0.0
    if costs:
        unit = "seconds"
    else:
        costs = costs_from_trajectories(artifacts, rewards)

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    figure_failures(causes, rewards, out_dir / "figure1_failures.png", source)
    figure_score_cost(costs, rewards, out_dir / "figure3_score_cost.png", unit)

    for name in ("figure1_failures.png", "figure3_score_cost.png"):
        print(f"wrote {out_dir / name}")
    print(f"tasks: {len(rewards)}  mean reward: {sum(rewards.values())/len(rewards):.4f}")
    print(f"causes: {dict(causes.most_common(6))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
