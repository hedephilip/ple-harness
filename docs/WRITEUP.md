# Kaggle writeup — every field filled, ready to paste

Deadline on the form: **Jan 6 2027, 7:59 AM GMT+8**. The checklist needs Basic
Details (title, subtitle, card, track), Project Description and Project Links
before Submit enables.

This version contains **no placeholders**. Where a measurement has not been made,
the text says so in plain words instead of showing a blank or a guess: the dev
set has not been run, and `rules.md` requires artifacts to come from
`eval/run.py` with the declared model, so no dev number can be written here
without fabricating it.

Three blocks are marked `[REPLACE AFTER DEV RUN]` **outside** the paste text.
They are the only places that change once the run exists.

---

## Field: Title (max 80)

```
Gated Harness: the gate recomputes the engineering, not the prose
```

65 characters.

## Field: Subtitle (max 140)

```
Python gates re-open every deliverable, recompute its numbers, and hand the agent a signed failure it can repair.
```

113 characters.

## Field: Card and Thumbnail Image (560 × 280)

Upload `docs/figures/card.png` — exactly 560 × 280, produced by
`python scripts/make_figures.py`.

## Field: Submission Track

`Main Track` (single track, auto-selected by the form).

## Field: Media gallery

`docs/figures/architecture.png` (1200 × 660). No video: videos must be hosted on
YouTube, and a still diagram is more honest than narration over results that do
not exist yet.

## Field: Project Description

Paste the block below verbatim, from the `#` heading to the end of §5.

---

# Gated Harness: compliance is the floor, not the score

- Repo: https://github.com/hedephilip/ple-harness
- Commit SHA: `188fc1f17bbd4da32aecfaeb7a0e82fc04161d60` — the tree in which
  the harness code was last changed. Commits after it touch documentation
  only: `git diff --stat 188fc1f HEAD -- '*.py'` is empty.
- Primary model_api: google-cloud/claude-opus-5-5
- Other models tested: none yet — the second model run is not done, so §3 reports
  design intent rather than a measured comparison
- Dev score (29 tasks): not measured. `artifacts/` has not been generated, so no
  dev score, cost per task or minutes per task can be reported

## 1. Insights & Failures (25 pts)

The scoring rule, not the model, set the design. Per `rules.md`, a
constraint-and-objective task scores each deliverable item as
`s = 0.4p + 0.6·G·O'`, with `G = 1` only when **every** hard constraint is met.
Compliance therefore caps an item at `0.4p`; the `0.6` term is paid only for a
design that beats its naive baseline. A harness that stops at "all checks pass"
collects the first term and calls it done.

Four findings shaped the build, each from a failure we reproduced:

- **Declared-path discovery was blind.** The path regex matched no `zip` and no
  `py`, and a `.strip("./")` removed the leading slash, so
  `/filesystem/.../submission.zip` was read as workdir-relative and never
  resolved. Counted from `eval/dev_set.yaml`: 14 of 29 dev tasks deliver a
  folder, 12 a `submission.zip`, 2 a `.py`, 1 an `.ifc`. The gate layer was
  reading almost none of them.
- **Discovery never left the workdir.** `find . -maxdepth 3` cannot see
  `/filesystem`, where a dozen dev tasks write their package. A marker is now
  written at task start and discovery unions `find /app /filesystem -newer`.
- **Unconditional gates were the largest defect.** A one-line smoke task — write
  a file containing `HELLO` — was failed twice, for carrying no claims block and
  no revision table, and four model rounds were spent demanding artefacts nobody
  asked for. Gates now declare `applies(ctx)` and decline what they cannot judge.
  Measured on that task: repair rounds 4 → 1, model calls 5 → 2,
  tokens 320/40 → 128/16.
- **The verdict was contaminating graded output.** `artifacts.md` exports
  `final_message.md` per task and 14 of 29 dev tasks are graded with it. Writing
  a gate status into that summary argues against the submission in the one place
  the grader reads. It now goes out as a `log` frame.

### 1.1 Failure Breakdown

A full breakdown by discipline needs `gates.csv` from a dev run, which does not
exist yet. What we can show is the taxonomy the gate layer distinguishes, because
every one was hit during construction: misread drawing values (a claim whose
number disagrees with the recomputation), code-clause errors (a clause named but
not satisfied), unit mismatches (a value with no declared unit, or two documents
disagreeing), solver non-convergence (Colebrook–White failing to reach residual
<1e-9), rounding errors (a takeoff that rounds down), and early stops (a task that
ends with no readable deliverable). Each is a distinct `cause_code`, so a repair
lesson never crosses from one to another.

### 1.2 Ablations

Dev-set ablations require two full runs and are not available. The engineering
ablations below were measured on the kit's smoke task and the local end-to-end
test, and they are the ones that changed behaviour:

| Change | Measure | Before | After |
|:-|:-|:-:|:-:|
| Conditional gates (`applies(ctx)`) | protocol requests | 5 | 2 |
| | repair rounds | 4 | 1 |
| | tokens in / out | 320 / 40 | 128 / 16 |
| | grader-facing summary | carried a gate verdict | agent's words only |
| Acquisition (folders, zip, docx) | formats read | `md`, `txt` | + folders, `submission.zip`, `.docx`, `.xlsx` |
| | discovery scope | `/app`, depth 3 | `/app` + `/filesystem`, mtime-bounded |
| | protocol requests | 2 | 5 |

Requests are not monotonic across these changes: conditional gates take
them from 5 to 2, then acquisition returns them to 5, because opening a
folder or a package costs one read per member. Tokens stay at 128/16
throughout, since the model is called twice either way.

**Two things that failed or surprised us.** First, *"a gate that always runs is
the safe choice."* It is not. A false positive costs more than a missed check,
because the repair loop pushes the agent to edit a deliverable the rubric already
scores, to satisfy a check the grader never asked about — the gate can lower the
score it was meant to protect. Second, *"discovering the deliverables once,
before the agent runs, is enough."* It gates an empty folder and fails every check
vacuously; discovery has to follow each turn, because the files only exist after
the agent writes them.

## 2. Architecture & Reasoning (25 pts)

`serve.py` holds a protocol-v1 WebSocket (`ping_interval=None`, one reader, 8
concurrent requests, always a `done` or `error` at the end). `harness.py` runs one
agent turn, executes the model's tool calls as protocol requests, then re-reads
the artifacts and runs the gate registry. Six invariants are enforced in code,
not in prompt text:

1. **Authority separation** — the judge never reads the model's summary.
2. **Re-derivation** — every deliverable is re-opened and its text extracted
   (folders enumerated, zips opened in-process, `.docx`/`.xlsx` parsed as zip+XML
   with the standard library, so the build keeps one dependency) before any check
   runs.
3. **Strict pass** — `all_hard_pass([])` is `False`; a gate that raises becomes a
   hard failure, never a silent success.
4. **Signed failure** — `(gate_id, cause_code, observed, limit, unit)` plus a
   stable signature, so two failures of equal magnitude but different cause never
   share a lesson.
5. **Conditional memory** — lessons live outside the context window, at most one
   per repair round, admitted only on a verified fail→pass flip for that artifact.
6. **Bounded repair** — finite rounds, then a hard stop.

**One dev task against an engineer's workflow — `lv-cable-sizing`.** Its declared
deliverable is a `submission.zip` under
`/filesystem/electrical__lv_cable_sizing__blind/output/`. An engineer sizes the
feeder from load, applies the continuous-load factor, checks voltage drop per
segment and then cumulatively across the run, and issues a package. The harness
mirrors that sequence mechanically: resolve the declared path, open the package,
read the calculation text, require the claims block to carry its inputs with
declared units, then recompute ampacity at 1.25× continuous, the per-segment drop
against 3%, and the cumulative drop against 5%. A takeoff that rounds down is a
hard failure with a signed cause, not a style note. The engineer's judgement —
which code edition governs, which revision supersedes which — is handled by a
revision-authority gate that ranks AHJ > Addendum > RFI > IFC > Preliminary
rather than trusting the corpus order.

## 3. Cross-Model Generalizability (15 pts)

Not yet measured. Running two families is the next experiment after the dev set,
and the harness was built to make it cheap: nothing in the gate layer is model
specific, because gates read files rather than messages.

| model_api | Baseline | Yours | Delta | Tokens in/out/cached | $/task |
|:-|:-:|:-:|:-:|:-:|:-:|
| google-cloud/claude-opus-5-5 | not run | not run | — | — | — |
| google-cloud/gemini-4-argon | not run | not run | — | — | — |

What we expect to hold across models, and why: acquisition, gating and the
`final_message` rule are file-level and therefore model-independent. What we
expect to vary is repair efficiency — how many rounds a weaker model needs before
a signed failure is acted on — which is exactly what one lesson per round and a
round budget are there to bound.

## 4. Efficiency & Scaling (20 pts)

A score-versus-cost curve needs the dev run. The measured datapoint we have is
the kit smoke task: 5 protocol requests (reads, not model calls), 128 input / 16
output tokens, 1 second, one gate round. That is a plumbing measurement, not a
performance claim.

The design bounds cost in three places rather than by hoping: repairs are
round-budgeted rather than token-budgeted; exactly one lesson is injected per
round, so the context does not grow into a transcript of everything that ever
failed; and `MAX_STEPS_PER_ROUND` caps tool misuse inside a turn, which is where
an unpriced loop usually hides. Token usage is reported per model call through
`usage` frames, so the cost column is measured rather than estimated once the run
exists.

## 5. Reproducibility (15 pts)

At the SHA above:

```bash
uv run python -m kit check ../ple-harness      # submission.yaml, files, build, model, listen, smoke
uv run python -m kit artifacts ../ple-harness  # artifact rules, no Docker needed
python -m unittest discover -s tests           # 47 tests, no network
python tests/e2e_local.py                      # gate reject → repair → pass over a real WebSocket
```

Stated exactly as it stands: `kit check` passes `submission.yaml`, `files`,
`build`, `model`, `listen` and `smoke` on this tree. `mcp` warns because the
harness exposes no MCP client. `artifacts` warns because the dev set has not been
run, so `kit artifacts` does not pass yet and this writeup does not claim it does.
The 47 tests and the end-to-end WebSocket test pass with no network.

---

## Field: Project links

```
https://github.com/hedephilip/ple-harness
```

## Field: Files

Nothing to upload. `artifacts/` belongs in the repository, not in a writeup
attachment — `artifacts.md` caps one deliverable at 95 MiB and the folder at
512 MiB, and the kit checks the committed folder, not an upload.

## Field: DOI

Optional. It creates a DOI after the competition closes and changes nothing about
judging.

---

## [REPLACE AFTER DEV RUN] — three blocks only

Everything above is final except these. Replace them once `artifact` exists;
nothing else in the paste text changes.

**1. Header line.** Replace

```
- Other models tested: none yet — the second model run is not done, so §3 reports
  design intent rather than a measured comparison
- Dev score (29 tasks): not measured. `artifacts/` has not been generated, so no
  dev score, cost per task or minutes per task can be reported
```

with the real figures from `artifacts/manifest.json` and
`scripts/report_telemetry.py`:

```
- Other models tested: google-cloud/gemini-4-argon
- Dev score (29 tasks): <mean reward> | $<x>/task | <n> min/task
```

Also update the Commit SHA to the submission commit
(`git rev-parse HEAD` after `artifacts/` is committed).

**2. §1.2.** Replace the engineering table with the dev ablation table the form
expects — `enforce=False`, `+ acquisition`, `+ conditional gates`, submitted —
with columns Dev (29), Str (4), Civ (9), Elec (9), Mech (7), $/task. Two
`eval/run.py` runs produce it. Keep the "two things that failed" paragraph; it is
still true.

**3. §3 and §4.** Fill the two rows and add the score-vs-cost figure.

## Why nothing is invented here

The form scores §1.2, §3 and §4 on measurement — together with the ablation table
inside §1.2, that is more than half the rubric. Writing plausible numbers into
those cells would read better and would be a fabricated claim about work that has
not been done, in a competition whose `rules.md` explicitly requires artifacts to
come from `eval/run.py` with the declared model. A judge comparing this writeup to
the repository would find no `artifacts/`, and the entry would be disqualified
rather than scored. The honest version is weaker and survives contact with the
repo.
