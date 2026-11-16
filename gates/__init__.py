"""Gate modules. Importing this package registers every gate into verify.GATES.

Adding a discipline means adding one file here and one import line below —
never touching the repair loop in serve.py.
"""
from gates import cross, structural, electrical, mechanical, civil  # noqa: F401

from verify import GATES

DISCIPLINES = ("structural", "civil", "electrical", "mechanical")


def gate_index() -> dict[str, list[str]]:
    """gate_id list per task type, for docs and for the run-start sanity check."""
    return {
        discipline: [getattr(fn, "__name__", "unnamed") for fn in GATES.gates_for(discipline)]
        for discipline in DISCIPLINES
    }


def assert_registered() -> None:
    """Fail fast at server start if a discipline silently lost its gates."""
    index = gate_index()
    empty = [name for name, fns in index.items() if len(fns) <= len(GATES._cross)]
    if empty:
        raise RuntimeError(f"no discipline gates registered for: {empty}")
