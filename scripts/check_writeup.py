"""Check the Kaggle writeup fields before they are pasted into the form.

Two failures this prevents, both silent:

1. A title or subtitle over the form's character limit is rejected at paste
   time, after the description is already in.
2. `docs/WRITEUP_DESCRIPTION.md` is what gets pasted, while `docs/WRITEUP.md`
   is what gets edited. If they drift, the submitted text is not the reviewed
   text. This recomputes the extraction and fails on any difference.

    python scripts/check_writeup.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WRITEUP = ROOT / "docs" / "WRITEUP.md"
DESCRIPTION = ROOT / "docs" / "WRITEUP_DESCRIPTION.md"
TITLE_MAX = 80
SUBTITLE_MAX = 140


def extract_description(text: str) -> str:
    """The paste block: from the entry heading to the Project links field."""
    start = text.index("# Gated Harness: compliance is the floor, not the score")
    end = text.index("## Field: Project links")
    block = text[start:end].rstrip()
    return re.sub(r"\n-{3,}\s*$", "", block).rstrip() + "\n"


def fenced_after(text: str, heading: str) -> str:
    match = re.search(re.escape(heading) + r"[^\n]*\n+```\n([^\n]+)\n```", text)
    if not match:
        raise SystemExit(f"could not find a fenced value under {heading!r}")
    return match.group(1)


def main() -> int:
    writeup = WRITEUP.read_text(encoding="utf-8")
    problems: list[str] = []

    title = fenced_after(writeup, "## Field: Title")
    subtitle = fenced_after(writeup, "## Field: Subtitle")
    if len(title) > TITLE_MAX:
        problems.append(f"title is {len(title)} chars, limit {TITLE_MAX}")
    if len(subtitle) > SUBTITLE_MAX:
        problems.append(f"subtitle is {len(subtitle)} chars, limit {SUBTITLE_MAX}")

    expected = extract_description(writeup)
    actual = DESCRIPTION.read_text(encoding="utf-8")
    if actual != expected:
        problems.append("WRITEUP_DESCRIPTION.md has drifted from WRITEUP.md; "
                        "re-run the extraction")

    if "{{" in actual:
        problems.append("description still contains a placeholder token")
    # The Overview's Stage 1 rubric, by name: coverage of all five is a minimum
    # requirement, so the headings must say what the rubric says.
    for heading in ("## 1. Insight & Failure Analysis", "## 2. Engineering Reasoning",
                    "## 3. Cross-Model Generalizability", "## 4. Efficiency & Scaling",
                    "## 5. Clarity & Visuals"):
        if heading not in actual:
            problems.append(f"description is missing {heading!r}")

    print(f"title    {len(title):>3}/{TITLE_MAX} chars")
    print(f"subtitle {len(subtitle):>3}/{SUBTITLE_MAX} chars")
    print(f"description {len(actual.split()):>4} words, "
          f"{len(actual)} chars, 5 sections")

    if problems:
        for problem in problems:
            print(f"FAIL {problem}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
