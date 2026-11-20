"""Rewrite the paste block from `docs/WRITEUP.md`.

`WRITEUP.md` is what gets edited; `WRITEUP_DESCRIPTION.md` is what gets pasted
into the Kaggle form. They are the same text, and `check_writeup.py` fails when
they drift. This regenerates the derived file from the source so the two cannot
disagree:

    python scripts/sync_description.py        # write the block
    python scripts/sync_description.py --check # exit 1 if it is stale
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from check_writeup import DESCRIPTION, WRITEUP, extract_description


def main() -> int:
    expected = extract_description(WRITEUP.read_text(encoding="utf-8"))
    current = DESCRIPTION.read_text(encoding="utf-8") if DESCRIPTION.is_file() else ""
    if "--check" in sys.argv:
        if current != expected:
            print("WRITEUP_DESCRIPTION.md is stale; run scripts/sync_description.py")
            return 1
        print("WRITEUP_DESCRIPTION.md is in sync")
        return 0
    if current == expected:
        print("already in sync")
        return 0
    DESCRIPTION.write_text(expected, encoding="utf-8")
    print(f"wrote {DESCRIPTION} ({len(expected.split())} words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
