# Remaining risks and limitations

Written against the competition Overview's minimum requirements and the Stage 1
rubric. Ordered by consequence, not by difficulty.

## 1. The entry is not currently eligible

`artifacts/` has never been generated, so `kit check` reports
`ready: false, unready: "artifacts"`. The Overview requires committed dev outputs
and a passing `kit artifacts`, and the judge re-scores those artifacts. Without
them two of the three required figures cannot exist either, because they are
plots of that data.

**What clears it:** one dev run on a model endpoint, then committing the output.

```bash
uv run python eval/run.py /mnt/c/dev/ple-harness
python scripts/make_result_figures.py
git add -A && git commit -m "PLE harness submission"
```

**Residual risk after that:** none of the eligibility gates themselves, but the
run costs money and time, and a partial run leaves a task at `0` — the mean is
over all 29.

## 2. Forty points of the rubric are unmeasured

| Criterion | Points | State |
|---|---|---|
| Insight & Failure Analysis | 25 | partly: engineering ablations measured, dev ablation table empty |
| Engineering Reasoning | 25 | complete |
| Cross-Model Generalizability | 15 | **empty** — needs two models on 29 tasks |
| Efficiency & Scaling | 20 | partly: cost mechanics described, no score-vs-cost curve |
| Clarity & Visuals | 15 | complete |

§1.2 and §3 cannot be filled by reasoning; they need runs. A submission that
leaves them empty competes on roughly 65 of 100 points.

## 3. The declared model probably cannot clear the prize floor

`submission.yaml` declares `google-cloud/llama-4-maverick` by request. The
competition requires a mean of at least 0.138 for the Pareto frontier; the paper
places this model family below 7%. The harness would have to add more than seven
points on its own, and the published spread across seven harnesses for one model
is about three. Treat prize eligibility as forfeited unless that line changes.

## 4. Gate coverage is narrow by design

Thirteen formula gates across four disciplines, against an average of 25.3
graded checks per task. The gates verify what can be recomputed from a claims
block; they cannot verify a rubric judge's judgement, and 14 of the 29 dev tasks
are rubric-graded. On those, the harness contributes structure and a clean
closing summary, not correctness checking.

**Why not add more gates:** every gate added without a task to calibrate against
risks a false positive, and a false positive is the expensive error here — it
drives the agent to edit a deliverable the rubric already scores.

## 5. Untested against the real task corpus

All verification is against hand-built fixtures and the kit's synthetic tasks.
The gates have never run on a real PLE environment with its superseded revisions,
CAD files and multi-format deliverables. The acquisition layer is tested on the
shapes counted from `dev_set.yaml` (folders, zips, `.docx`, `.xlsx`, absolute
`/filesystem` paths) but not on a real one.

## 6. Protocol and platform

- **MCP**: implemented and exercised by the kit's `mcp` stage, but never against
  a real third-party app server. A malformed SSE stream or an unexpected
  session-replay rule could still fail at evaluation time; the failure is
  contained (the server is skipped, the shell still works).
- **Time budget**: the reserve is 5% of `agent_timeout_sec`, capped at ten
  minutes. If a single model call outlives that reserve, the run still overruns
  and the deliverable may be truncated.
- **Egress**: only the model endpoint is reachable. Anything the harness might
  want from a URL is unavailable, by rule.

## 7. Things that would change the verdict

1. A dev run producing `artifacts/` — moves the entry from ineligible to scored,
   and fills §1.2, §3, §4 and two figures.
2. A gate-fidelity check on real tasks — if false positives exceed a few percent,
   the honest submission is `enforce=False` plus a writeup that says so.
3. Switching the declared model back to one that can clear 0.138 — recovers prize
   eligibility at roughly $17/task on the frontier model, per the paper's own
   cost table.
