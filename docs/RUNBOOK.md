# Runbook — producing `artifacts/` and finishing the entry

Everything below is blocked only by compute. The repository, the harness, the
writeup and the checks are done; what remains is one dev run.

## Why this has not been run here

Measured on the machine this repository was built on:

| Requirement | Available | Verdict |
|---|---|---|
| ~10 GB free for base and world images | 7.2 GB | short |
| Docker Desktop 16.25 GB RAM for the largest dev task | 8.2 GB configured | short |
| Inference | Intel Iris Xe, no CUDA | CPU only |
| Per-task limit | 360 minutes | a 29-task pass is days on CPU |

`eval/run.py` downloads the corpus with `snapshot_download` and **builds a Docker
image per task** before the agent starts, so the disk figure is not optional.

## Prerequisites

```bash
# once
uv tool install harbor==0.20.0 --with websockets
docker desktop start          # WSL integration must be enabled for the distro
```

The dataset (`google/physical-engineerings-last-exam`, `gated=auto`) serves
anonymously — no `HF_TOKEN` is required for the dev set, which was verified by
fetching its tree without credentials.

## Mode 1 — validate the repository (seconds, no model)

```bash
cd ../ple-ref
uv run python -m kit check ../ple-harness
uv run python -m kit artifacts ../ple-harness
```

Expect seven of eight stages to pass and `artifacts` to warn until Mode 3 runs.

## Mode 2 — one task, against any endpoint (minutes to hours)

Useful for proving the harness against a real corpus without committing a poor
dev score.

```bash
uv run python -m eval.run ../ple-harness \
    --tasks fire-test-validation-memo \
    --model-base-url http://127.0.0.1:11434/v1 \
    --env-file /path/to/model.env
```

If the model is Ollama on the Windows host and Docker runs in WSL, the container
reaches the host through Docker's bridge gateway, so Ollama must listen beyond
loopback:

```powershell
$env:OLLAMA_HOST = '0.0.0.0:11434'; ollama serve
```

A 3B CPU model will call tools but often emits empty arguments, so expect empty
deliverables. That is a pipeline test, not a score.

## Mode 3 — the full dev set (what the entry needs)

One run produces `artifacts/`, which is what the competition grades.

```bash
uv run python -m eval.run ../ple-harness --env-file /path/to/model.env
```

`MODEL_PROXY_URL` and `MODEL_PROXY_KEY` come from the kit's model proxy; any
OpenAI-compatible endpoint works, and the Overview permits generating artifacts
on a personal or open-weight model as long as the model used is documented.

## After the run

```bash
python scripts/make_result_figures.py      # Figures 1 and 3 from manifest.json
python scripts/check_submission.py         # expect 0 fails
git add -A && git commit -m "PLE harness submission"
```

Then, in `docs/WRITEUP.md`:

1. Replace the header's dev-score line with the real mean from
   `artifacts/manifest.json`, and the SHA with `git rev-parse HEAD`.
2. Replace §1.2's engineering table with the dev ablation (`enforce=False` vs
   `enforce=True`, two runs).
3. Fill §3 with two models and §4 with the score-versus-cost figure.
4. Re-run `python scripts/check_writeup.py` — it enforces the 2,000-word cap and
   fails if the description drifts from `WRITEUP.md`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `refusing to draw: … not written by eval/run.py` | hand-made manifest | expected; only a real run may produce figures |
| `ImageNotBuilt` | task image failed to build | free disk, then retry that task |
| model unreachable from the container | endpoint bound to loopback | bind `0.0.0.0`, or use a hosted URL |
| `kit check` rebuilds for ~2 minutes | images were pruned to free space | expected; it rebuilds once |

## What is already verified

81 tests, the protocol end-to-end test, seven of eight `kit check` stages, a
1,981-word writeup with rubric-matched headings, and a commit SHA that resolves
to the code snapshot. The open items are all measurements, not code.
