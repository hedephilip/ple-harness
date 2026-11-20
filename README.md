# gated-harness

An agent harness for [Physical-Engineering's Last Exam](https://ple-bench.com/).
The model proposes; a deterministic gate layer dispossesses.

The premise comes from a single published number: on co-authored PLE tasks the
best agent satisfied **91%** of individual constraints but only **41.3%** of its
deliverables cleared every hard safety check (Google Cloud blog, 3 Nov 2026).
Google states the scoring mechanic directly — agents *"only earn points if
their design passes every hard safety check first."* So the binding constraint
is not reasoning quality. It is whether the deliverable survives an
independent check.

This harness therefore puts the check outside the decoder.

## What is verified, and what is not

| Component | Status |
|---|---|
| Gate layer (`verify.py`, `gates/`) | **Tested.** 31 gate fixtures, a fidelity matrix, 11 request-shape tests and a time-budget guard, 76 tests in total; 13 discipline gates and 6 cross-cutting gates, `python -m unittest discover -s tests` |
| Deliverable acquisition (`protocol.deliverables_of`, `harness._discover`, `extract.py`) | **Tested.** Absolute paths, folders, `submission.zip`, `.docx`, `.xlsx` — the shapes `eval/dev_set.yaml` actually uses |
| Repair loop, playbook admission, telemetry | **Tested.** 5 loop tests with a scripted client |
| `submission.yaml`, repo layout, strict-pass semantics | Matches the published competition contract |
| WebSocket protocol (`protocol.py`) | **Verified** against `docs/protocol.md` v1 in `google-research/ple` — frame shapes, `cancel`, `usage`, size and concurrency limits |
| End-to-end run | **Verified.** `python tests/e2e_local.py` spawns `serve.py`, drives it over a real WebSocket with a fake evaluator and a scripted model, and observes gate reject → repair → pass → `done` |
| `artifacts/` | **Not generated.** Requires `uv run python eval/run.py` with the competition repo and a model endpoint |

Nothing above is claimed beyond what was actually run.

## Layout

```
submission.yaml   contract manifest
serve.py          WebSocket entrypoint; binds 0.0.0.0:$PORT
harness.py        agent loop + gated completion boundary
protocol.py       wire format (isolated; the only file the protocol touches)
llm.py            one OpenAI-compatible client + provider capability flags
verify.py         gate registry, strict-pass semantics, result schema
gates/
  cross.py        deliverables, claims, units, numeric agreement, revisions, requirements
  structural.py   AISC 360-16 LRFD
  electrical.py   NEC 2023 ampacity, segment + cumulative vdrop, takeoff
  mechanical.py   Darcy-Weisbach, pump power, 25-year LCC
  civil.py        prismoidal earthwork, clearance, consolidation settlement
playbook.py       conditional failure memory (verified-recovery admission only)
telemetry.py      gate-fire CSV — the Figure 3 data, written during the run
tests/            gate self-audit + loop tests
scripts/          report_telemetry.py (Figure 3), gate_fidelity.py (oracle safety)
```

## The six invariants

1. **Authority separation** — the model never certifies its own output.
2. **Re-derivation** — gates recompute capacity from raw inputs; a reported
   `phi_Mn` is ignored and recalculated from `Fy` and `Zx`.
3. **Strict pass** — empty result set, timeout, or exception is a failure.
   `all_hard_pass([])` returns `False`, and there is a test for it.
4. **Signed failure** — every failure carries `(gate_id, cause_code,
   observed, limit, unit)`, so the repair prompt is generated, not written.
5. **Conditional memory** — lessons live on disk, one per round, admitted only
   after the same gate flips fail→pass on the same artifact path.
6. **Bounded repair** — `MAX_FIX_ROUNDS`, then a hard stop reported as failure.

## Deliverable contract

Every deliverable must carry a claims block so the gate can recompute:

```markdown
<!-- PLE-CLAIMS
{
  "units": {"structural.Fy_ksi": "ksi", "structural.Zx_in3": "in^3"},
  "structural": {"Fy_ksi": 50, "Zx_in3": 100, "Mu_kip_ft": 300,
                 "d_in": 16, "tw_in": 0.4, "Vu_kip": 150,
                 "L_span_in": 360, "delta_L_in": 0.8},
  "revisions": [{"doc_id": "S-201", "rank": "IFC", "revision": 1, "value": 11.0}]
}
-->
```

A number without a declared unit fails. A quantity stated twice with two values
fails. A document that loses to a higher-ranked revision cannot supply a
governing value.

## Running

```bash
python -m unittest discover -s tests -v      # 76 tests, no network, no deps
python tests/e2e_local.py                    # spawns serve.py, needs websockets only
PORT=8080 MODEL_API=google-cloud/glm-5.2 python serve.py
```

Dev sweep against the competition kit:

```bash
uv run python eval/run.py ../ple-harness
uv run python -m kit check ../ple-harness
uv run python -m kit artifacts ../ple-harness
```

## Measuring the claim

The whole argument rests on one ablation. `PLE_GATE_MODE=off` runs the same
agent with gates evaluated but non-blocking, so the two arms differ only in
whether a failure triggers a repair round:

```bash
PLE_GATE_MODE=on  ...   # enforcement arm
PLE_GATE_MODE=off ...   # control arm
python scripts/report_telemetry.py telemetry/tasks.csv telemetry/gates.csv
```

Report `G=1 rate`, mean score, rounds used and token delta for both arms. If
the delta is small, say so — a negative result honestly reported is worth more
than a claim the numbers do not support.

## Known gaps

- **Two staged gaps, measured.** `kit check` on this tree passes `submission.yaml`, `files`, `build`, `model`, `listen` and `smoke` (bundle 110 MiB, image built in ~100 s, websocket accepted 2 s after start, smoke task one gate round with a clean `final_message`). It carries an MCP client for the task's Streamable HTTP transport (`initialize`, `tools/list`, `tools/call`, JSON or SSE replies), so app servers are reachable without shelling into the container — seven of eight stages pass. It warns on `artifacts`, which do not exist until the dev set is run. `ready: false`, `unready: "artifacts"`.
- Deliverable paths are parsed from `instruction` text, because the protocol carries none. Heuristic — validate on the dev set before trusting the contract gate.
- Gates cover the four disciplines' core checks, not every clause in every code.
- Gate coverage is unequal across disciplines, and the split of the 56 hidden tasks is not published, so effort is allocated by the published 85-task benchmark instead: mechanical 30, electrical 27, civil 18, structural 10. Mechanical and electrical are therefore the largest missing returns; structural, with three formula gates, is the best covered.
- Claude Opus 5.5 is both the strongest published solver and the model the paper uses to judge rubric items (paper sec.5.1). Worth stating rather than leaving it to be noticed: the harness drives the same family that grades the rubrics, which is a coincidence of the setup and not something this entry exploits.

## Licensing, provenance and competition data

- **Harness code** — Apache-2.0 (`LICENSE`). Required by Rules B(5)(a).
- **Documentation and the Kaggle Writeup** — CC BY 4.0. See
  [docs/COMPLIANCE.md](docs/COMPLIANCE.md) §4.
- **Provenance.** The harness is original work written for this competition.
  `protocol.py` implements `docs/protocol.md` — documentation, not code — and no
  file from `kit/`, `sample_submissions/` or any other entrant's repository was
  copied into this tree. Gate formulae are implemented from the published codes
  and are covered by hand-computed fixtures in `tests/`, not by benchmark
  reference values. Rules C(14)(a) requires this warranty; the tree is small
  enough (35 files, 0.28 MB) for a judge to check it.
- **Competition Data is not in this repository and never will be.** Rules
  B(4)(b) prohibit redistributing task corpora, environments, graders or
  reference deliverables. `.gitignore` enforces this. Every gate fixture in
  `tests/` is a hand-computed value from a published formula, not benchmark
  data.

## Reproducibility

Required by Rules B(7)(a)(i) — the code must be *capable of generating the
winning Submission*, with the resource requirements described.

| Item | Value |
|---|---|
| Runtime | Python 3.12, `uv`-managed venv at `/opt/harness/venv` |
| Dependencies | `requirements.txt` — `websockets` only; the gate layer, and the `.docx`/`.xlsx`/`.zip` readers, are stdlib |
| Build | `install:` in `submission.yaml`, runs once as root with internet |
| Serve | `serve: /opt/harness/venv/bin/python {src}/serve.py` on `0.0.0.0:$PORT` |
| Model access | injected by the evaluator proxy via `MODEL_BASE_URL` / `MODEL_API_KEY` |
| Dev evaluation | `uv run python eval/run.py ../ple-harness` |
| Contract checks | `uv run python -m kit check` and `uv run python -m kit artifacts` |
| Tests | `python -m unittest discover -s tests` — 76 tests, no network |
| Gate fidelity | `python tests/test_fidelity.py` — every gate driven by a valid case and a perturbation |
| Writeup fields | `python scripts/check_writeup.py` — title/subtitle limits and description drift |
| CI | `.github/workflows/tests.yml` runs the two commands above on every push, plus `tests/e2e_local.py` |

Environment variables consumed: `PORT`, `MODEL_API`, `MODEL_NAME`,
`MODEL_BASE_URL`, `MODEL_API_KEY`, plus `MAX_FIX_ROUNDS`, `PLAYBOOK_PATH`,
`TELEMETRY_DIR`, `PLE_GATE_MODE`.

## Citing PLE

This harness is built for the PLE benchmark. If you use it in research, cite the
benchmark as the competition's Acknowledgements request:

```bibtex
@misc{han2026ple,
  title         = {{PLE}: Physical-Engineering's Last Exam},
  author        = {Rujun Han and Yufan Zhuang and Arijit Ray and Han Yu and
                   Zhongying CuiZhu and George Lee and Yifei Ming and Binz Roy and
                   Varun Sakalkar and Vishy Tirumalashetty and Burak Gokturk and
                   Tomas Pfister and Chen-Yu Lee},
  year          = {2026},
  eprint        = {2610.30537},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  url           = {https://arxiv.org/abs/2610.30537}
}
```
