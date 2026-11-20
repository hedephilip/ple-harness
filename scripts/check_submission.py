"""Check the entry against the competition's Stage 1 minimum requirements.

Source: the competition Overview page, "Minimum Requirements" and "Submission
Requirements". Those are eligibility gates, not scoring: an entry that misses one
is not judged at all. The kit checks the repository; this checks the rest —
the writeup's word cap and figures, the SHA, the licence, the model list, and
whether artifacts/ is in the same commit.

    python scripts/check_submission.py

Exit code 1 means at least one hard requirement fails.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "docs" / "WRITEUP_DESCRIPTION.md"
SUBMISSION = ROOT / "submission.yaml"
ARTIFACTS = ROOT / "artifacts"

# Overview page, "Sponsored Models".
ALLOWED = {
    "google-cloud/gemini-4-argon", "google-cloud/gemini-3.8-flash",
    "google-cloud/gemini-3.1-pro-preview", "google-cloud/gemma-4-26b",
    "google-cloud/claude-opus-5-5", "google-cloud/gpt-oss-120b",
    "google-cloud/glm-5.2", "google-cloud/llama-4-maverick",
}
WORD_LIMIT = 2000
CATEGORY_LIMIT_MIB = 512
FILE_LIMIT = 10_000

rows: list[tuple[str, str, str]] = []   # (status, requirement, detail)


def add(status: str, requirement: str, detail: str = "") -> None:
    rows.append((status, requirement, detail))


def check_submission_yaml() -> None:
    if not SUBMISSION.exists():
        add("FAIL", "submission.yaml present", "missing")
        return
    text = SUBMISSION.read_text(encoding="utf-8")
    add("PASS", "submission.yaml present")
    match = re.search(r"^model_api:\s*(\S+)", text, re.M)
    model = match.group(1).strip("\"'") if match else ""
    if model in ALLOWED:
        add("PASS", "model_api is one of the 8 sponsored models", model)
    else:
        add("FAIL", "model_api is one of the 8 sponsored models", f"got {model!r}")
    for key in ("name", "install", "serve"):
        add("PASS" if re.search(rf"^{key}:", text, re.M) else "FAIL",
            f"submission.yaml declares {key}")


def check_license() -> None:
    path = ROOT / "LICENSE"
    if not path.exists():
        add("FAIL", "LICENSE present", "missing")
        return
    head = path.read_text(encoding="utf-8", errors="replace")[:600].lower()
    if "apache license" in head:
        add("PASS", "LICENSE is Apache-2.0")
    elif "mit license" in head:
        add("PASS", "LICENSE is MIT")
    else:
        add("FAIL", "LICENSE is Apache-2.0 or MIT", "neither detected in the header")


def check_entry_files() -> None:
    for name in ("serve.py", "harness.py"):
        add("PASS" if (ROOT / name).exists() else "FAIL", f"{name} at the repo root")


def check_artifacts() -> None:
    if not ARTIFACTS.is_dir():
        add("FAIL", "artifacts/ unpacked and committed", "no artifacts/ directory")
        return
    manifest = ARTIFACTS / "manifest.json"
    if not manifest.is_file():
        add("FAIL", "artifacts/manifest.json present", "missing")
        return
    try:
        json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add("FAIL", "artifacts/manifest.json parses", str(exc))
        return
    files = [p for p in ARTIFACTS.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    add("PASS", "artifacts/manifest.json parses", f"{len(files)} files, "
        f"{size / 2**20:.1f} MiB")
    if size > CATEGORY_LIMIT_MIB * 2**20:
        add("FAIL", "artifacts under 512 MiB", f"{size / 2**20:.0f} MiB")
    if len(files) > FILE_LIMIT:
        add("FAIL", "artifacts under 10,000 files", str(len(files)))


def check_same_commit() -> None:
    """The overview requires code, submission.yaml and artifacts/ in one commit."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%H", "--", "artifacts"],
                             cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        add("WARN", "artifacts in the same commit as the code", str(exc))
        return
    if not out:
        add("FAIL", "artifacts in the same commit as the code",
            "artifacts/ has never been committed")
    elif out == head:
        add("PASS", "artifacts in the same commit as the code")
    else:
        add("WARN", "artifacts in the same commit as the code",
            f"last artifacts commit {out[:7]} is not HEAD {head[:7]}")


def check_writeup() -> None:
    if not DESCRIPTION.exists():
        add("FAIL", "writeup description present", "missing")
        return
    text = DESCRIPTION.read_text(encoding="utf-8")
    words = len(text.split())
    add("PASS" if words <= WORD_LIMIT else "FAIL",
        f"writeup under {WORD_LIMIT} words", f"{words} words")

    # Presence and shape are not enough: the string has to name a commit that
    # exists in this repository and is reachable from HEAD, otherwise it points
    # at nothing a judge can check out.
    sha = re.search(r"\b[0-9a-f]{40}\b", text)
    if not sha:
        add("FAIL", "40-character commit SHA at the top", "no 40-hex string")
    else:
        value = sha.group(0)
        try:
            exists = subprocess.run(["git", "cat-file", "-e", value + "^{commit}"],
                                    cwd=ROOT, capture_output=True, timeout=20).returncode == 0
            ancestor = exists and subprocess.run(
                ["git", "merge-base", "--is-ancestor", value, "HEAD"],
                cwd=ROOT, capture_output=True, timeout=20).returncode == 0
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            add("WARN", "40-character commit SHA at the top", str(exc))
            return
        if not exists:
            add("FAIL", "SHA names a commit in this repository", value[:12])
        elif not ancestor:
            add("FAIL", "SHA is reachable from HEAD", value[:12])
        elif value == head:
            add("PASS", "SHA pins the submitted code", "it is HEAD")
        else:
            # A commit cannot contain its own hash, so the writeup is always
            # committed after the snapshot it names. What must hold is that
            # nothing runtime changed in between: then the pin still describes
            # the submitted code, and only documentation followed it.
            try:
                changed = subprocess.run(
                    ["git", "diff", "--name-only", value, head, "--", "*.py"],
                    cwd=ROOT, capture_output=True, text=True, timeout=20
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError) as exc:
                add("WARN", "SHA pins the submitted code", str(exc))
                return
            if changed:
                add("FAIL", "SHA pins the submitted code",
                    f"code changed after {value[:12]}: {changed.splitlines()[:3]}")
            else:
                add("PASS", "SHA pins the submitted code",
                    f"{value[:12]}; commits after it are documentation only")

    add("PASS" if "github.com/hedephilip/ple-harness" in text else "FAIL",
        "repository URL in the writeup")

    # "Coverage of all 5 Stage 1 rubric criteria" is a minimum requirement, so the
    # headings have to name the criteria as the rubric names them.
    rubric = ["Insight & Failure Analysis", "Engineering Reasoning",
              "Cross-Model Generalizability", "Efficiency & Scaling",
              "Clarity & Visuals"]
    missing = [name for name in rubric if name not in text]
    add("PASS" if not missing else "FAIL",
        "writeup covers the 5 rubric criteria",
        "all five headings present" if not missing else f"missing {missing}")

    # Three figures are required: architecture, score-vs-cost, failure breakdown.
    figures = {
        "architecture diagram": r"(?i)architecture",
        "score-vs-cost plot": r"(?i)score[- ]versus[- ]cost|score[- ]vs[- ]cost|Figure 3",
        "failure breakdown": r"(?i)figure 1|failure breakdown",
    }
    for label, pattern in figures.items():
        add("PASS" if re.search(pattern, text) else "FAIL",
            f"writeup references the {label}")

    # Counted by name, not by number: two stray plots are not the three figures
    # the Overview names.
    required = {
        "architecture diagram": "architecture.png",
        "score-vs-cost plot": "figure3_score_cost.png",
        "failure breakdown": "figure1_failures.png",
    }
    figures_dir = ROOT / "docs" / "figures"
    for label, filename in required.items():
        exists = (figures_dir / filename).is_file()
        add("PASS" if exists else "FAIL", f"figure file for the {label}", filename)


def main() -> int:
    check_submission_yaml()
    check_license()
    check_entry_files()
    check_artifacts()
    check_same_commit()
    check_writeup()

    width = max(len(r[1]) for r in rows)
    for status, requirement, detail in rows:
        print(f"{status:4}  {requirement:<{width}}  {detail}")

    hard = [r for r in rows if r[0] == "FAIL"]
    print()
    print(f"{sum(1 for r in rows if r[0] == 'PASS')} pass, "
          f"{sum(1 for r in rows if r[0] == 'WARN')} warn, {len(hard)} fail")
    if hard:
        print("Not submittable until the FAIL rows clear.")
        return 1
    print("All Stage 1 minimum requirements met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
