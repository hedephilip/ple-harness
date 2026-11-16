# Gate contract

This document defines what a gate is allowed to do, so that adding a gate
cannot quietly weaken the layer.

## 1. A gate is a pure function

```python
def my_gate(ctx: dict) -> list[GateResult]
```

- No network, no model calls, no wall-clock dependence.
- Reads only `ctx` — which is built by re-reading artifacts from disk.
- Raises freely: a raising gate is converted to a hard failure, never a pass.

`ctx` shape:

```python
{
  "task_type": "structural",          # one of the four disciplines
  "deliverables": ["memo.md", ...],   # declared output paths
  "files": {"memo.md": b"..."},       # bytes read back from disk
  "data": {                           # parsed from the PLE-CLAIMS blocks
      "structural": {...},
      "revisions": [...],
  },
}
```

## 2. Result schema

| Field | Meaning |
|---|---|
| `gate_id` | stable snake_case identifier, unique within a run |
| `passed` | bool |
| `cause_code` | UPPER_SNAKE failure class; the primary playbook key |
| `observed` / `limit` / `unit` | the numbers the repair prompt quotes back |
| `severity` | `hard` blocks completion; `soft` feeds the score only |

`cause_code` is not decoration. Playbook retrieval keys on
`(gate_id, cause_code, magnitude bucket)`. Two failures of the same magnitude
but different cause must not share a lesson — a plausible but wrong lesson is
worse than none.

## 3. Strict-pass semantics

| Situation | Verdict |
|---|---|
| Every hard gate reports `passed=True` | PASS — and only then may `done` be sent |
| Empty result set | FAIL |
| No hard results at all | FAIL |
| Gate raises | FAIL, `cause_code=GATE_ERROR` |
| Gate returns `None` | FAIL, `cause_code=GATE_ERROR` |
| Only soft gates fail | PASS, contributes to score not completion |

There is a test for each row in `tests/test_gates.py::TestStrictSemantics`.

## 4. Deliverables must be acquired before they can be judged

A gate can only judge what `_collect` managed to read. Measured against the
public dev set (`eval/dev_set.yaml`): 14 tasks deliver a folder, 12 a
`submission.zip`, 2 a `.py` and 1 an `.ifc`. A gate layer that assumes "one
`.md` file in the workdir" reads almost nothing and declines every check.

The acquisition contract, in order:

1. **Parse the prompt for exact paths** (`protocol.deliverables_of`). Paths stay
   absolute: `/filesystem/.../submission.zip` is not a path relative to `/app`.
   Extensions include `zip`, `py`, `ifc`, `dxf`, `dwg`; a folder is a path with
   a trailing `/`.
2. **Discover what changed on disk.** `touch /tmp/.ple_start` at task start, then
   `find /app /filesystem -type f -newer /tmp/.ple_start`. Discovery must leave
   the workdir; dev-set deliverables live under `/filesystem` too.
3. **Expand folders and packages.** `read_file` refuses directories, so a folder
   deliverable is enumerated with `find <dir> -type f` and its children read
   individually. A `.zip` is opened in-process (`extract.archive_members`) and
   its text members are exposed as `<zip>!<member>`.
4. **Extract text from the format, not the extension.** `.docx`, `.xlsx` and
   `.pptx` are zip archives of XML and are read with the standard library.
   Binary formats that hide their text (`.pdf`, `.ifc`, `.dxf`) yield no text;
   gates must decline them rather than fail them.

`ctx` therefore carries `texts` (path → extracted text), `present` (paths that
exist and are non-empty, including folders and zip packages) and `files` (raw
bytes). Gates read `texts` and `present`; nothing re-filters by filename.

## 5. Adding a gate

1. Add the function to the right module in `gates/`, decorated with
   `@GATES.register("<discipline>")` or `@GATES.register_cross`.
2. Return `ok(...)` or `fail(...)` — never a bare bool.
3. Add **two** fixtures in `tests/`: one that must pass and one that must fail.
   The must-pass fixture must be hand-worked from the governing formula, not
   produced by the gate. A gate that rejects a correct answer is worse than no
   gate at all.
4. Run `python -m unittest discover -s tests`.

## 6. What gates must not do

- Must not read the model's message history or its self-reported results.
- Must not accept a capacity the model computed; recompute it from inputs.
- Must not return early with success when required keys are missing — a missing
  input is `BAD_INPUT` or `GATE_ERROR`, both failures.
- Must not consult the playbook. Retrieval belongs to the loop, not the gate.
