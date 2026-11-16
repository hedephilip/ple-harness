# Gated Harness — PLE submission writeup

> **Fill these five fields after the dev run, before uploading. Nothing else in
> this document needs editing.**
>
> | Field | Where it comes from |
> |---|---|
> | `{{DEV_SCORE}}` | mean of `tasks.*.reward` in `artifacts/manifest.json` |
> | `{{TASKS_WITH_ARTIFACTS}}` | number of task folders under `artifacts/` (out of 29) |
> | `{{COMMIT}}` | `git rev-parse HEAD` of the submitted commit (40-char SHA) |
> | `{{ARTIFACTS_SIZE}}` | `du -sh artifacts/` |
> | `{{RUN_DATE}}` | date `eval/run.py` finished |
>
> If any placeholder cannot be filled honestly, delete the sentence that
> contains it rather than estimating. A writeup with no score line is
> survivable; a fabricated score is not.

## 1. What this entry is

A WebSocket harness for the PLE agent protocol, paired with a deterministic gate
layer that re-reads the deliverables from disk and recomputes them. The model
proposes; Python disposes. Nothing the model *claims* in its message is treated
as evidence.

The design starts from the scoring rule rather than from the model. Per
`docs/rules.md` §Scoring, a constraint-and-objective task scores each
deliverable item as

```
s = 0.4 p + 0.6 G O'        O' = clip((O - O_naive) / (1 - O_naive), 0, 1)
```

where `G` is `1` only if **every** hard constraint is met, so breaking one caps
the item at `0.4`, and `O_naive` is an unoptimised but compliant baseline.

Two consequences shape every decision below.

**First, compliance is not enough.** A naive design that satisfies all
constraints earns no objective credit. Feasible-but-unoptimised therefore scores
the same `0.4 p` as infeasible on the 0.6 term. The gate cannot be only a
filter that rejects bad work; it has to define the feasible region and let the
work improve inside it.

**Second, the loss is at item level, not constraint level.** The PLE results
report that the strongest configuration satisfied 91% of individual constraints
on co-authored tasks while only 41.3% of its deliverable items cleared every
hard gate (Google Cloud blog, 3 Nov 2026). Separately, across all runs of the 86
model/harness pairs, 23.2% score zero — and of those, 70.4% delivered files that
the grader scored zero anyway (paper §5, failure analysis). The gap between
"almost every constraint" and "the pair clears the gate" is where score is lost,
and it is mechanical rather than conceptual.

## 2. Architecture

Six invariants, each enforced in code rather than in prompt text:

1. **Authority separation.** `harness.py` drives the model; `verify.py` and
   `gates/` judge the output. The judge never reads the model's summary.
2. **Re-derivation.** `_collect` re-opens every deliverable from the task
   container and extracts its text before any gate runs.
3. **Strict pass.** `all_hard_pass([])` returns `False`. An empty result set is
   not a pass; a gate that raises becomes a hard failure (`GATE_ERROR`), never a
   silent success.
4. **Signed failure.** Every failure carries `(gate_id, cause_code, observed,
   limit, unit)` and a stable signature so two failures with the same magnitude
   but different causes do not share a lesson.
5. **Conditional memory.** Lessons live outside the context window, at most one
   is injected per repair round, and a lesson is admitted only on a verified
   fail→pass flip for that artifact.
6. **Bounded repair.** Finite rounds, then a hard stop. No unbounded
   self-correction.

The gate layer covers four disciplines — structural (flexure, shear,
deflection), electrical (ampacity at 1.25× continuous, segment and cumulative
voltage drop, carton rounding), mechanical (Colebrook–White friction factor
solved iteratively to residual <1e-9, head loss, pump power, 25-year NPV) and
civil (prismoidal volume, buffer clearance, settlement) — plus cross-cutting
gates for deliverable presence, claims blocks, unit declarations, numeric
agreement between documents, requirement listing, and revision authority
(AHJ > Addendum > RFI > IFC > Preliminary).

## 3. Three decisions that differ from a plain gated harness

### 3.1 Gates decline what they cannot judge

The first version ran the cross-cutting gates on every task. A one-line smoke
task — write a file containing `HELLO` — was then failed twice, for carrying no
claims block and no revision table, and four model rounds were spent demanding
artefacts the task never asked for.

That is the failure mode worth designing against, because it is not merely
wasteful. PLE's expert-authored deliverables are predominantly `.docx` and
`.xlsx`, formats a filename-based gate cannot read. A gate that fails them pushes
the agent to modify a deliverable the rubric already scores, to satisfy a check
the grader never asked about. The gate makes the submission worse.

Gates now declare an `applies(ctx)` predicate. `claims_present` applies only to
the four engineering disciplines and only where readable text exists;
`unit_declarations` only when a claims block is present; `numeric_agreement` only
with two or more blocks to compare; `requirements_listed` only when the task asks
for requirements or code clauses; `revision_authority` only when revisions exist
or the task speaks of conflicting documents. When every gate declines, the
harness reports a **coverage gap, not a failure**, and does not repair.

### 3.2 Deliverables are acquired, not assumed

Counted from `eval/dev_set.yaml`: of 29 dev tasks, 14 deliver a folder, 12 a
`submission.zip`, 2 a `.py` and 1 an `.ifc`. A harness that assumes "one `.md`
file in the workdir" reads almost none of them.

`deliverables_of` parses the exact paths from the prompt and keeps them absolute
(`/filesystem/.../submission.zip` is not a path relative to `/app`). Discovery
then unions those with `find /app /filesystem -type f -newer /tmp/.ple_start`,
written once at task start, so only files this run produced are considered.
Folders are enumerated because `read_file` refuses directories; zip packages are
opened in-process; `.docx`/`.xlsx`/`.pptx` are read as zip archives of XML with
the standard library, so the build keeps a single dependency.

One detail that matters: text runs inside a docx are joined **without**
separators. Joining with spaces turns `<!--` into `<! --` and silently destroys
the claims marker the gate searches for.

### 3.3 The verdict stays out of `final_message`

`docs/artifacts.md` exports `final_message.md` per task and says a task scores
zero when it has "nothing to grade"; `dev_set.yaml` marks `final_message: true`
for 14 of 29 tasks. The closing summary is graded input.

The first version appended `[gated] unresolved hard-gate failures after 4
round(s)` to it, which argued against the submission in its own summary. The gate
verdict now goes out as a `log` frame; `final_message` carries the agent's words
verbatim.

## 4. Engineering evidence

This section states what has actually been run. It is not a score.

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | 47 tests, no network |
| `python tests/e2e_local.py` | real WebSocket, fake evaluator, scripted model: gate reject → repair → pass → `done` in 2 rounds |
| `python -m kit check` | `build`, `model`, `listen`, `smoke` pass against the committed tree; smoke reports `final message 'done'` in one gate round |

The smoke stage earned its place: it is what exposed the four acquisition
defects and the unconditional cross gates, all of which passed a unit suite.

## 5. Dev-set results

`artifacts/` produced by `eval/run.py` on `{{RUN_DATE}}`, harness commit
`{{COMMIT}}`, `{{TASKS_WITH_ARTIFACTS}}` of 29 tasks with usable artifacts,
`{{ARTIFACTS_SIZE}}`.

Local dev score: **`{{DEV_SCORE}}`**.

Per-task scores are the `reward` field in `artifacts/manifest.json`; the
harness's own telemetry (`tasks.csv`, `gates.csv`) is written alongside each run
for inspection and is never read by the harness at run time.

## 6. Limitations, stated plainly

- **The rubric half is not gate-addressable.** 14 of 29 dev tasks are graded by
  an LLM judge against a rubric (`grading: rubric`); a mechanical gate cannot add
  a point there. What the harness contributes on those tasks is a complete
  deliverable at the exact path and an accurate closing summary.
- **Gate coverage is thin relative to the benchmark.** Twelve formulas and six
  cross-cutting checks against a benchmark averaging 25.3 checks per task. The
  gates that exist are correct and tested; they are not exhaustive.
- **No MCP client.** The harness exposes `exec`, `read_file` and `write_file`
  only, so tasks that serve documents or CAD as MCP servers are reachable
  through the shell alone. This is a real ceiling, not a stylistic choice.
- **No optimiser yet.** The `O'` half of the score is designed for but not
  implemented; the gate currently verifies feasibility and does not descend
  inside the feasible region.

## 7. Reproduce

```bash
uv run python -m kit check ../ple-harness      # container, protocol, smoke
uv run python eval/run.py ../ple-harness       # dev set, writes artifacts/
uv run python -m kit artifacts ../ple-harness  # artifact rules, no Docker
python -m unittest discover -s tests           # 47 tests, no network
```

## 8. Figures (optional, generate after the dev run)

1. **Score decomposition** — stacked bar per dev task: `0.4p` against the
   realised `0.6GO'`, from `tasks.csv`. Shows how much of each task is
   constraint credit versus objective credit.
2. **Gate outcomes** — pass/fail counts by `cause_code` from `gates.csv`, with
   the repair rounds they took. This is the honest picture of what the gate
   catches.
3. **Round cost** — model calls and wall seconds per repair round, from
   `tasks.csv`, against the 6-hour task budget.

All three are derived from files the harness already writes; none require a
second run.
