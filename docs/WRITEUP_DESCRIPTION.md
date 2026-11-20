# Gated Harness: compliance is the floor, not the score

- Repo: https://github.com/hedephilip/ple-harness
- Commit SHA: `2aeb7b2e319512c4a1773aea8bdd0654fcb2d334` — the tree in which
  the harness code was last changed. Commits after it touch documentation
  only: `git diff --stat 188fc1f HEAD -- '*.py'` is empty.
- Primary model_api: google-cloud/llama-4-maverick
- Other models tested: none yet — the second model run is not done, so §3 reports
  design intent rather than a measured comparison
- Dev score (29 tasks): not measured. `artifacts/` has not been generated, so no
  dev score, cost per task or minutes per task can be reported

## 1. Insight & Failure Analysis (25 pts)

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
  `final_message.md` per task and 14 of 29 dev tasks are graded with it. The gate
  status goes out as a `log` frame rather than a verdict in the summary, but a run
  whose own gates failed still names the unverified checks in one line: silence
  there would let a failure read as a clean success.

- **The model client would have failed every evaluation call.** It attached
  `temperature` to every request, and `docs/models.md` states that
  `google-cloud/claude-opus-5-5` returns `400` if `temperature`, `top_p`, `top_k`
  or a thinking budget is present. The kit's stub accepts any body, so five local
  checks passed while the entry was unscoreable. The field is now absent unless
  explicitly configured, `max_tokens` defaults to the recommended 32000, and Claude
  requests carry the two cache breakpoints it needs — without them every turn
  re-processes the whole conversation, which across a six-hour task is the
  difference between affordable and not.

### 1.1 Failure Breakdown

Figure 1 (failures by discipline and type) needs `gates.csv` from a dev run. That
run has not been made, so the figure is not drawn and no estimate is substituted
for it. What is measured instead is the failure that costs most: a gate firing on
a valid deliverable. Every gate is driven both ways — a hand-computed compliant
case that must stay green, and one single-parameter perturbation that must trip it
with a specific cause code. All 13 formula gates and all 6 cross-cutting gates pass
in both directions: **0 false positives, 0 false negatives across the 19-gate
suite.** The cases derive from the formulae, not from benchmark values, so the
suite can tell a correct gate from one that agrees with itself. `python tests/test_fidelity.py` prints the matrix.

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
unchanged is a wasted turn. Eleven tests assert the shape; the stub cannot.

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
| google-cloud/llama-4-maverick | not run | not run | — | — | — |
| google-cloud/gemini-4-argon | not run | not run | — | — | — |

What we expect to hold across models, and why: acquisition, gating and the
`final_message` rule are file-level and therefore model-independent. What we
expect to vary is repair efficiency — how many rounds a weaker model needs before
a signed failure is acted on — which is exactly what one lesson per round and a
round budget are there to bound.

## 4. Efficiency & Scaling (20 pts)

Figure 3, score versus cost, needs the dev run and is therefore not drawn. The measured datapoint we have is
the kit smoke task: 5 protocol requests (reads, not model calls), 128 input / 16
output tokens, 1 second, one gate round. That is a plumbing measurement, not a
performance claim.

The six-hour limit is enforced rather than hoped for. The harness reads
`agent_timeout_sec` from the task frame, reserves 5% of it (capped at ten
minutes, floored at two), and stops repairing while that reserve is still
intact — so the last thing it does is finalise a deliverable, not truncate one.
Protocol section 4 allows ten seconds after `cancel`, enough to describe a
deliverable and not enough to produce one. Two tests pin this, including that a
task with no time limit is never cut short.

Declaring an open-weight model puts this entry at the cheap end of the cost
axis and, per the paper, in the weakest performance band, so the score has to
come from the gate layer or not at all.

The design bounds cost in three places rather than by hoping: repairs are
round-budgeted rather than token-budgeted; exactly one lesson is injected per
round, so the context does not grow into a transcript of everything that ever
failed; and `MAX_STEPS_PER_ROUND` caps tool misuse inside a turn, which is where
an unpriced loop usually hides. Token usage is reported per model call through
`usage` frames, so the cost column is measured rather than estimated once the run
exists.

## 5. Clarity & Visuals (15 pts)

### 5.1 Reproducibility

At the SHA above:

```bash
uv run python -m kit check ../ple-harness      # 8 stages
uv run python -m kit artifacts ../ple-harness  # no Docker needed
python -m unittest discover -s tests           # 80 tests, no network
python tests/test_fidelity.py                  # per-gate matrix: valid case vs perturbation
python tests/e2e_local.py                      # gate reject → repair → pass over a real WebSocket
```

`kit check` passes seven of its eight stages on this tree: `submission.yaml`,
`files`, `build`, `model`, `listen`, `smoke` and `mcp`, the last exercising the
app-server path end to end (9 requests, 192 in / 24 out tokens). The eighth,
`artifacts`, warns because the dev set has not been run; `kit artifacts` does not
pass and this writeup does not claim it does.

No dev scores were generated, so no judge model applies; the declared Stage 2
model is `google-cloud/llama-4-maverick`.

Reference: R. Han et al., *PLE: Physical-Engineering's Last Exam*,
arXiv:2610.30537, 2026.
The 80 tests and the end-to-end WebSocket test pass with no network.
