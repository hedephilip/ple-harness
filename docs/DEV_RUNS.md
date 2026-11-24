# Dev runs

Every number here comes from a committed artifact or a workflow log, and each
run names the commit that produced it. Nothing in this file is estimated.

The declared model for Stage 2 is `google-cloud/claude-opus-5-5`. No run below
uses it: this machine has no access to the Google-hosted gateway, so the runs
substitute a local Ollama model behind the kit's sanctioned LiteLLM proxy. The
proxy is reached exactly as `docs/models.md` prescribes — `MODEL_PROXY_URL`
pointing at a server that answers to the `google-cloud/*` names — so the harness
is exercised on the real request path. The *model quality* is not the declared
one, and every score below is therefore a plumbing measurement, not a
performance claim.

## Run 1 — one check-graded task, 2026-11-20

| | |
|:-|:-|
| Workflow run | [44674154293](https://github.com/hedephilip/ple-harness/actions/runs/44674154293) |
| Commit | `4dfa67c` |
| Task | `roof-deck-design` (checks grading, deliverable `output/submission.zip`) |
| Stand-in model | `qwen2.5:1.5b` on 4 vCPU |
| Outcome | `ended: ok`, reward **0.000**, **0 files** exported |
| Wall clock | 66 s |
| Tokens | 4,775 in / 908 out over 124 agent steps |

### What it actually did

The committed `trajectory.json` records 124 agent steps: **23 `exec` and 100
`read_file`, and not one `write_file`**. Every `exec` was a `find` command. The
agent enumerated the project folder, opened templates, ran out of steps, and
described the deliverable it had intended to write in its final message.

That produced three findings, each now fixed:

1. **A step budget cannot stop a discovery loop.** `MAX_STEPS_PER_ROUND` capped
   the round at 40; the loop consumed its rounds without ever writing. A
   read-only streak counter now injects exactly one reminder after 12
   consecutive non-writing steps, once per round.
2. **A missing input was reported as a broken gate.** With no claims block the
   discipline gates raised `KeyError: 'Fy_ksi'` and the run recorded
   `GATE_ERROR`. That message is not actionable, and it made a model failure
   read as a harness fault. `KeyError` is now `MISSING_INPUT` and names the
   field; `ValueError` deliberately stays `GATE_ERROR`, because it can be a
   gate's own arithmetic failing.
3. **The figure generator refused a real run.** It looked for a top-level
   `commit` key; `eval/run.py` writes `commit` inside `harness`, alongside
   `format`, `dev_set` and `tree`. The provenance guard now reads the real
   shape, so a genuine run draws and a hand-made fixture still cannot.

### Failure taxonomy the gates recorded

Taken from the run's own committed `final_message.md`, which lists every gate
it could not verify:

| cause code | count | meaning |
|:-|:-:|:-|
| `GATE_ERROR` | 3 | `KeyError` on an absent claims field — now `MISSING_INPUT` |
| `NO_CLAIMS_BLOCK` | 1 | the deliverable carried no machine-readable inputs |
| `MISSING_DELIVERABLE` | 1 | the declared `submission.zip` was never created |
| `REVISION_TABLE_MISSING` | 1 | no revision-authority table |

The verdict was not written into the message body as a second opinion: it is
appended as one line, `Unverified in this run: ...`, because `artifacts.md`
exports `final_message.md` to the grader and 14 of 29 dev tasks are graded with
it.

### Manifest shape

Reproduced here because the figure guard depends on it, and because it is the
shape every later run must match:

```json
{
  "format": 1,
  "dev_set": "<sha256 of the task set>",
  "created": "<ISO 8601>",
  "harness": {"name": "...", "model_api": "...", "tree": "<sha256>",
              "files": {"<path>": "<mode> <blob>"}, "commit": "<git sha>",
              "dirty": false},
  "tasks": {"<task id>": {"run": "...", "trial": "...", "ended": "ok",
                          "reward": 0.0, "tree": "<sha256>", "files": {...},
                          "final_message": "<sha256>"}}
}
```

## Earlier local runs

- `python -m unittest discover -s tests` — 84 tests, no network.
- `python tests/test_fidelity.py` — 19 gates driven both ways, 0 false
  positives and 0 false negatives.
- `python tests/e2e_local.py` — gate reject → repair → pass over a real
  WebSocket, against a scripted model.
- `uv run python -m kit check ../ple-harness` — 7 of 8 stages; `artifacts`
  warns until a dev run is committed.

## Run 2 — the stand-in never writes a deliverable, 2026-11-24

A 29-job matrix (one dev task per job, `shards: auto`) ran the full dev set on
`qwen2.5:7b`. It establishes the limit that blocks the artifacts requirement,
so it is recorded here rather than in the writeup as a score.

| | |
|:-|:-|
| Workflow run | `45305481461` |
| Commit | `b2e5278` |
| Outcome | 14 jobs failed at the artifacts guard, 1 passed, 14 still running at the time of writing |
| Usable deliverables | **0** |

Two trajectories, counted from their own `tool_calls`:

| task | steps | `exec` | `read_file` | `write_file` | files under `files/` |
|:-|:-:|:-:|:-:|:-:|:-:|
| `data-hall-mep-routing` | 12 | 6 | 4 | **0** | 0 |
| `roof-deck-design` | 125 | 23 | 100 | **0** | 0 |

`data-hall-mep-routing` ends by announcing it "cannot directly read images" and
will assume typical layouts. `roof-deck-design` spends 100 reads and then
describes the package it intended to write. Neither model call ever emits a
`write_file`, so the guard's verdict is correct: `nothing this task's grader
reads: no file under files/`.

The one job that passed did so on an incidental file, not a deliverable —
`engineers-estimate-check` recorded `app/tools/.apps_data/.coordinator/config/config.json`,
reward `0.0`, with a 91-byte `final_message.md`. A file the harness captured from
the project folder is not a deliverable and must not be presented as one.

This also means the artifacts currently committed from run 1 are **refused** by
`kit artifacts`: `roof-deck-design` has no `files/` directory, so "no dev task in
artifacts/ has usable artifacts". A Stage 1 entry must pass `kit artifacts`, so
this is the blocker to clear before submission, not a telemetry gap.

## Reproducing a run

```
gh workflow run dev-run -f tasks=data-hall-mep-routing,data-center-site-model,lv-cable-sizing -f model=qwen2.5:3b
```

Requires the `HF_TOKEN` repository secret: the task dataset is gated, and a
metadata request answers 200 without access while a blob request answers 403.
The workflow probes a real blob and fails with that distinction rather than a
generic error.
