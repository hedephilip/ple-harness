# Conclusion — what is proven, what is not, what decides

Written after re-reading `docs/rules.md`, `docs/artifacts.md`,
`eval/dev_set.yaml`, `kit/check.py` and the paper's results section, and after
the smoke stage exposed four defects in this harness. Supersedes any earlier
optimism in this repository's notes.

## 1. Readiness

**Not ready to submit.** `kit check` reports `ready: false` with one unready
item: `artifacts`.

`artifact` is not a formality. `docs/rules.md` §Dev score: the committed
`artifacts/` are graded by each dev task's grader, a task without usable
artifacts scores `0`, and the dev score is the mean over all 29 tasks. Generating
them needs a real model behind `MODEL_PROXY_URL`; a stub cannot produce gradable
work, and artifacts produced against a stub would be worthless and would
misrepresent the entry.

**One action clears it:**

```bash
uv run python eval/run.py /mnt/c/dev/ple-harness   # then commit artifacts/
```

## 2. What is proven

| Claim | Evidence |
|---|---|
| Speaks the v1 WebSocket protocol | `kit check` → `listen` PASS, `smoke` PASS against the real relay |
| Container builds and starts within limits | `kit check` → `build` PASS; server listens on `0.0.0.0:$PORT` |
| Model calls route through the egress proxy | `kit check` → `model` PASS |
| Gate → repair → pass loop works over the real protocol | `tests/e2e_local.py`: reject, repair, pass, `done` in 2 rounds |
| Gate arithmetic is correct on worked examples | 30 hand-computed fixtures in `tests/test_gates.py` |
| Deliverables are acquired in the shapes the dev set uses | 10 fixtures in `tests/test_delivery.py`: folder, `submission.zip`, `.docx`, `.xlsx`, absolute `/filesystem` paths |
| Grader-facing summary is not contaminated | `e2e`: `final_message` = the agent's words; verdict arrives as a `log` frame |

Total: 76 tests, no network, including a fidelity matrix that drives every one
of the 19 gates with a valid case and a single-parameter perturbation, and 11
request-shape tests that assert what the client sends to each sponsored model.

## 3. What is not proven

1. **Dev score.** Zero. No `artifacts/`, no `manifest.json`, no reward figures.
2. **Gate fidelity.** No confusion matrix against the dev graders. This is the
   decisive unknown: a gate that rejects a deliverable the grader accepts costs
   score directly, and today's smoke run already produced one class of false
   positive. The rate on real tasks is unmeasured.
3. **That the gate arm beats the ablation arm.** `enforce=False` exists and is
   logged, but the comparison has not been run.

## 4. Retractions

Three figures used earlier in this work are **not supported** by the current
sources and must not appear in the writeup or the submission:

- a `0.138` score floor — not in `docs/rules.md`, not returned by the
  competition site;
- "Top 100 of 36 qualify" — same;
- a cost-Pareto frontier requirement — same.

`docs/rules.md` states that how entries are evaluated and ranked will be
announced. Until it is, treat ranking as unpublished and size the work on score,
not on placement.

## 5. Competitive position, honestly

The gate architecture is **not** a differentiator by itself. The public Code tab
already shows multiple gate-based notebooks; external gates are the entry fee.

What the sources do support as a differentiator:

- **`O'` is the untouched half of the score.** `0.4 p` is constraint credit;
  `0.6 G O'` is only paid when `G = 1` *and* the design beats the naive
  baseline. A harness that stops at "all gates pass" collects `0.4 p` and calls
  it done.
- **Item-level clearance, not constraint fraction, is the loss.** 91% of
  constraints versus 41.3% of deliverable items clearing every hard gate (Google
  Cloud blog).

Magnitude: the paper's seven harnesses for a fixed model span 47.3%–50.6%
(corresponding to Claude Opus 5.5 in the results table), so a harness can move a
fixed model by single-digit points. An earlier estimate of roughly `+6` points
in this repository assumed item-level clearance gains across co-authored tasks
generally. With 14 of 29 dev tasks graded by rubric, that estimate is **too
high** and should be treated as an upper bound, not a forecast.

## 6. What decides it

In order:

1. **Generate artifacts** (needs a real model). Everything below is unmeasurable
   without them.
2. **Run the gate-vs-grader comparison** with `scripts/gate_fidelity.py` on the
   dev set. It stops on false positives by design. If false positives exceed a
   few percent, the honest submission runs the ablation arm (`enforce=False`)
   and the writeup says so.
3. **Extend item-level gates into mechanical and electrical**, the two largest
   disciplines and the two where published scores are lowest.
4. **Implement `O'` descent** — bounded search over cost-driving parameters
   inside the feasible region, evaluated by the gates, with no model tokens.

## 7. The one-sentence version

The harness is protocol-correct, container-verified, and engineered around the
scoring rule rather than around the model — but **it has no measured score, and
its central risk (gate false positives) is unquantified**; the single run that
would justify any competitive claim is the dev set with a real model, and the
credential for that is the only thing standing in the way.
