# Strategy — what actually moves the score

Everything below is measured from the PLE paper (arXiv 2610.30537v2, §3–§6),
the live Kaggle page, and the public discussion board, read 16 Nov 2026.
Claims I could not verify are marked as such at the end.

---

## 1. The field is smaller and earlier than it looks

| Signal | Value |
|---|---|
| Entrants | 1,975 |
| Teams that actually submitted | **36** |
| Public writeups | **0** — the tab is empty |
| Discussion topics | 15, almost all infrastructure: kit check after self-hosting, whether the largest dev tasks fit in 16 GB RAM, dev-time model access, a requested dry-run server |

The competitive set is 36 teams, not 2,000 people. And since **Top 100 advance**
to Stage 2, Stage 1 is a compliance gate rather than a filter. Completing a
valid, measured submission is itself differentiating — most of the field is
still fighting the packaging.

---

## 2. The scoring engine, exactly

Equation 1 of the paper:

```
s = 0.4·p + 0.6·G·O′
```

- `p` — fraction of all constraints passed (rubric-style)
- `G ∈ {0,1}` — the hard-constraint gate (safety, feasibility)
- `O′` — objective score; for cost tasks `O = c_bound / c`, normalised against a naive baseline

**A hard-gate failure does not score zero.** It scores `0.4p`. The correct
statement is that `G=0` *caps* the score at 0.40 and forfeits the entire 0.6
term. That distinction matters because it tells you where to spend effort: the
0.6 term is 60% of the score and it is gated on a binary.

---

## 3. Where the 0.6 is actually lost

For Claude Opus 5.5 in Claude Code — the best configuration that exists:

> *"on co-authored tasks, its deliverable items satisfy 91% of their constraints
> on average, yet only 41.3% of the items satisfy every hard constraint and so
> earn objective credit under eq.1"*

Two things to note. First, the unit is **deliverable items**, not deliverables.
Second, the 0.6 term fires on 41.3% of items while 91% of individual constraints
pass. **That gap — 49.7 points of item-level credit — is the entire competition.**

Failure distribution across all runs (86 model×harness pairs):

| Share of all runs | Outcome |
|---|---|
| 76.8% | score > 0 |
| 23.2% | score 0% |
| ↳ 25.3% of those zeros | no gradable deliverable at all |
| ↳ 4.3% | time budget or agent-side crash |
| ↳ 70.4% | **deliver files that the grader scores 0** — of which 2,020 runs on eq.1 tasks, 817 rubric-graded, and **726 at all-or-nothing gates** (site design, MEP coordination) |

That last cell is the cheapest win on the board: 726 runs produced a file that
scored zero at a single all-or-nothing check. A clash or an unserved row zeroes
an entire task.

---

## 4. The quantified case for a gate layer

Sensitivity of the score to item-level hard-constraint clearance `c`:

```
Δs ≈ 0.6 · Δc · O′
```

With `O′ ≈ 0.5`, moving item clearance by **+10 points is worth about +3 points
of score**; +15 points is worth about +4.5.

Compare that to the alternative lever. The paper measures harness spread for a
fixed model at **0.7–12.1 points, median 3.0**. For Claude Opus 5.5 across all
seven public harnesses: 47.3%–50.6%, a 3.3-point range.

So: a gate layer that lifts item-level hard-constraint clearance by 10+ points
is worth roughly the entire published harness spread, and it compounds on top of
whatever harness you already use. That is the only lever in this competition
that a two-person team can pull harder than Google can.

---

## 5. Per-discipline reality

Best configuration, mean of three runs, all 85 tasks:

| Discipline | Score | Share of the 56 hidden tasks |
|---|---|---|
| Civil | 69.9% | 9 |
| Structural | 46.6% | 6 |
| **Mechanical** | **40.5%** | **23** |
| Electrical | not broken out separately in §5.2 | 18 |

Mechanical is both the largest hidden slice and the hardest. Civil is the
easiest and the smallest. This is the opposite of the usual instinct to start
with structural.

---

## 6. Corrections to what I argued earlier

Three of my prior conclusions were wrong. Stated plainly so they don't get
carried forward:

1. **"Cheap model + gates owns the low-cost frontier."** Dead. Below $0.20/task
   the open-weight models score **under 7%**, and Llama 4 Maverick scores 0.4%.
   The prize floor is 0.138. A gate layer cannot rescue a model that never
   produces a plausible deliverable — a gate can detect a wrong number, it
   cannot invent the engineering. Gates pay off in the **middle band**
   (Gemini 3.8 Flash 28.2% → Gemini 4 Argon 43.2%), not at the bottom.
2. **Shipping `glm-5.2`.** GLM 5.2 scores **25.3%** — roughly the median config
   (25.7%) and half of Opus. Choosing it concedes ~25 points before any harness
   work. `submission.yaml` is now set to `claude-opus-5-5`.
3. **"41.3% of deliverables."** It is 41.3% of *deliverable items*.

Also corrected: `s = 0.4p + 0.6·G·O′` is now **verified verbatim** from eq. 1 —
it was previously unsourced. And **GPT 6 Astra (48.3%), the paper's #2 model,
is not among the eight sponsored models**, so it is not available to us.

---

## 7. The plan, ranked by expected points

| # | Move | Expected delta | Cost |
|---|---|---|---|
| 1 | Switch `model_api` to `claude-opus-5-5` | **+25** vs GLM 5.2 | done, one line |
| 2 | Raise item-level hard-constraint coverage — gates must check at the same granularity the grader does | +3 to +5 | the real work |
| 3 | All-or-nothing pre-submission checks (hard clash, every row served) | converts whole-task zeros | low |
| 4 | Requirements-listing gate: clause + value, every requirement cited | graded directly; nobody builds this | low |
| 5 | Variance reduction — fixed deliverable structure, capped rounds | 15.4-point per-task spread is scored three times | medium |
| 6 | Publish **gate coverage** as the writeup's novel axis | rubric points, not score | low |

Move 4 deserves emphasis. The paper is explicit:

> *"The solver must also explicitly list the requirements it applied, each with
> clause and value from the associated grounding document. The grader checks the
> listed requirements against the references, so successful navigation of the
> corpus becomes a metric in the final grading."*

Corpus navigation is **scored**. A deterministic check that every applied
requirement is listed with clause and value is trivial to build and almost
certainly absent from the public harnesses.

---

## 8. What not to do

- **Don't chase prompt engineering.** The ceiling for harness-level changes is
  3.3 points on Opus. The gate layer is not competing on that axis.
- **Don't buy score with tokens.** The eight most expensive configurations cost
  $27–54 per task and still score 33.8%–49.3% — all below Opus at $17.18.
- **Don't spread thin across four disciplines.** Structural is 6 of 56 hidden
  tasks. Mechanical is 23 and the worst-scoring.
- **Don't trust a single run.** Per-task score range across three runs averages
  15.4 points; 105 of 595 task-harness cells span 30 points or more.

---

## 9. The cost problem, honestly

Stage 2 is free — Google supplies the key. **Local dev is not.** 29 dev tasks ×
3 runs ≈ 87 runs:

| Model | Cost/run | × 87 |
|---|---|---|
| Claude Opus 5.5 | $17.18 | **≈ $1,495** |
| Gemini 4 Argon | $8.21 | ≈ $714 |
| Gemini 3.8 Flash | $2.55 | ≈ $222 |
| Open-weight | < $0.20 | ≈ $17 |

The rules explicitly permit generating `artifacts/` on a cheap model and
switching `model_api` to a sponsored model before committing. So the honest plan
is: **ablate on Gemini 3.8 Flash or a personal key, commit those artifacts, and
declare the judge model in the writeup.** The risk must be stated, not hidden —
gate gains measured on a 28% model may not transfer to a 50% model, and the
writeup should say so. Testing on two models is rubric criterion 3 anyway.

---

## 10. What I did not verify

- The contents of the ten public notebooks — I read their titles and vote
  counts, not their code. Claims about what competitors do should stay at that
  level of confidence.
- Discussion thread bodies — titles only.
- Whether any competitor has already built a requirements-listing gate.
- Per-discipline electrical score, not broken out in the section I read.
