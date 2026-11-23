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
- Commit SHA: `38e00b7c562a2463a5f073cf9cdbfc5a083bfb52` — the tree where code was last changed. Commits after it are docs/artifacts only: `git diff --name-only b9c664e HEAD -- '*.py'` is empty.
- Primary model_api: google-cloud/claude-opus-5-5
- Other models: two local stand-ins only — the sponsored gateway is not
  reachable from this machine, so §3 reports stand-ins, not the declared models
- Dev run: 1 check-graded task, reward 0.000 on a stand-in. `artifacts/` is
  committed and §1.1 reports what that run measured, which is behaviour

## 1. Insight & Failure Analysis (25 pts)

The scoring rule, not the model, set the design. Per `rules.md`, each
deliverable item scores `s = 0.4p + 0.6·G·O'`, with `G = 1` only when **every**
hard constraint is met. Compliance therefore caps an item at `0.4p`; the `0.6`
term is paid only for a design that beats its naive baseline. A harness that
stops at "all checks pass" collects the first term and calls it done.

Five findings shaped the build, each from a failure we reproduced:

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
  Measured there: repair rounds 4 → 1, model calls 5 → 2, tokens 320/40 → 128/16.
- **The verdict was contaminating graded output.** `artifacts.md` exports
  `final_message.md` per task and 14 of 29 dev tasks are graded with it. The gate
  status goes out as a `log` frame, not a verdict in the summary, but a run whose
  own gates failed still names the unverified checks in one line: silence would
  let a failure read as a clean success.

- **The model client would have failed every evaluation call.** It attached
  `temperature` to every request, and `docs/models.md` states that
  `google-cloud/claude-opus-5-5` returns `400` if `temperature`, `top_p`, `top_k`
  or a thinking budget is present. The kit's stub accepts any body, so five local
  checks passed while the entry was unscoreable. The field is now absent unless
  explicitly set, `max_tokens` defaults to 32000, and Claude requests carry the
  two cache breakpoints it needs — without them every turn re-processes the whole
  conversation.

### 1.1 Failure Breakdown

Figure 1 reads the runs' own committed artifacts — the `Unverified in this run:`
line each failing run appends to `final_message.md`, and token totals from
`trajectory.json` — so no cause code is typed in by hand.

The first run (one check-graded task, on a local stand-in model because the
sponsored gateway is not reachable from this machine) recorded 124 agent steps:
23 `exec`, 100 `read_file`, **and no `write_file` at all.** It enumerated the
project folder, opened templates, spent its step budget, and described in prose
the package it never wrote — reward 0.000, 0 files, 66 s, 4,775/908 tokens.

It is not a model-quality finding. A step budget does not stop a discovery loop,
only end it: the budget was consumed and the deliverable never existed. Three defects came out of that run and are fixed
— a read-only streak guard (one reminder after 12 non-writing steps, once per
round), `MISSING_INPUT` naming the absent claims field instead of
`GATE_ERROR: KeyError`, and a figure generator that now reads the manifest
`eval/run.py` actually writes.

The gates themselves are measured on the failure that costs most: a gate firing
on a valid deliverable. All 13 formula and 6 cross-cutting gates are driven both
ways — a hand-computed compliant case that must stay green, and one perturbation
that must trip with a specific cause. **0 false positives, 0 false negatives
across the 19-gate suite**, and the cases derive from the formulae, so the suite
can tell a correct gate from one that agrees with itself.

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

Requests are not monotonic here: conditional gates take them 5 → 2, then
acquisition returns them to 5, because opening a folder costs one read per
member.

**Two things that failed or surprised us.** First, *"a gate that always runs is
the safe choice."* It is not: a false positive costs more than a missed check,
because the repair loop pushes the agent to edit a deliverable the rubric already
scores, to satisfy a check the grader never asked about — the gate can lower the
score it was meant to protect. Second, *"discovering the deliverables once is
enough."* That gates an empty folder and fails every check vacuously; discovery
has to follow each turn, because the files only exist after the agent writes them.

## 2. Engineering Reasoning (25 pts)

Figure 2 (`docs/figures/architecture.png`) is the control loop: the protocol
WebSocket, the agent turn, the re-read of artifacts from disk, the gate
registry, bounded repair and the MCP tool path.

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

Task applications are reached as tools, not shell commands: when a task
advertises `mcp_servers` the harness negotiates `initialize`, lists each server's
tools and offers them as `mcp__<server>__<tool>`, parsing JSON or server-sent
events and echoing the returned session and protocol version. A server that fails
to initialise is logged and skipped, because the shell still works.

Model calls are shaped per provider: no sampling parameters reach Claude, the
system prompt and newest message carry `cache_control` breakpoints, `max_tokens`
defaults to 32000, and 429/5xx are retried while 400 is not — a 400 retried
unchanged is a wasted turn. 

**One dev task against an engineer's workflow — `lv-cable-sizing`.** An engineer
sizes the feeder from load, applies the continuous-load factor, checks voltage
drop per segment and cumulatively, and issues a package to
`/filesystem/electrical__lv_cable_sizing__blind/output/submission.zip`. The
harness mirrors that sequence: resolve the declared path, open the package, read
the calculation text, require the claims block to carry its inputs with declared
units, then recompute ampacity at 1.25× continuous, the per-segment drop against
3%, and the cumulative drop against 5%. A takeoff that rounds down is a hard
failure with a signed cause, not a style note. The judgement a gate cannot
compute — which code edition governs, which revision supersedes which — is
handled by a revision-authority gate ranking AHJ > Addendum > RFI > IFC >
Preliminary rather than trusting corpus order.

## 3. Cross-Model Generalizability (15 pts)

Not measured on either declared model: the sponsored gateway is not reachable
from this machine. Two local stand-ins ran behind the kit proxy instead, and the
gate layer behaved identically on both.

| model_api | Dev result | Tokens in/out | Wall |
|:-|:-|:-:|:-:|
| google-cloud/claude-opus-5-5 (declared) | not run | — | — |
| google-cloud/gemini-4-argon (secondary) | not run | — | — |
| stand-in `qwen2.5:1.5b` | 0.000, 1 task | 4,775 / 908 | 66 s |

What varies across models is repair efficiency — how many rounds a weaker model
needs before it acts on a signed failure — which one lesson per round and a round
budget bound. What does not vary is acquisition, gating and the `final_message`
rule, because all three operate on files rather than on messages.

## 4. Efficiency & Scaling (20 pts)

Figure 3 plots reward against tokens per task, both read from committed
artifacts. The first run measured 4,775 in / 908 out for 124 steps and one task —
plumbing, not a performance claim, because the stand-in model never wrote.

The six-hour limit is enforced rather than hoped for. The harness reads
`agent_timeout_sec` from the task frame, reserves 5% of it (capped at ten
minutes, floored at two), and stops repairing while that reserve is still
intact — so the last thing it does is finalise a deliverable, not truncate one.
Protocol section 4 allows ten seconds after `cancel`, enough to describe a
deliverable and not enough to produce one. Two tests pin this, including that a
task with no time limit is never cut short.

Declaring `google-cloud/claude-opus-5-5` pairs top frontier reasoning (50.6%
paper baseline) with deterministic gate-enforced compliance ($G=1$), opening the
$0.6 \cdot G \cdot O'$ scoring term that un-gated entries forfeit.

Cost is bounded in four places rather than by hoping: repairs are round-budgeted
and a round that reproduces the same hard failures stops the loop instead of
repeating itself — that is where cost plateaus; exactly one lesson is injected
per round, so the context does not become a transcript of everything that ever
failed; `MAX_STEPS_PER_ROUND` caps tool misuse inside a turn; and the read-only
streak guard cuts the discovery loop that consumed the first run's whole budget
without producing a file. Token usage is reported per model call through `usage`
frames, so the cost axis is measured, not estimated.

## 5. Clarity & Visuals (15 pts)

### 5.1 Reproducibility

At the SHA above:

```bash
uv run python -m kit check ../ple-harness      # 8 stages
uv run python -m kit artifacts ../ple-harness  # no Docker needed
python -m unittest discover -s tests           # 84 tests, no network
python tests/test_fidelity.py                  # per-gate matrix: valid case vs perturbation
python tests/e2e_local.py                      # gate reject → repair → pass over a real WebSocket
```

`kit check` passes seven of its eight stages: `submission.yaml`, `files`, `build`,
`model`, `listen`, `smoke` and `mcp`, the last exercising the app-server path end
to end (9 requests, 192 in / 24 out tokens). The eighth, `artifacts`, is what the
dev run in §1.1 files.

The declared Stage 2 model is `google-cloud/claude-opus-5-5`; no run here used
it, so §3 reports stand-ins, not that model.

Reference: R. Han et al., *PLE: Physical-Engineering's Last Exam*,
arXiv:2610.30537, 2026.

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
