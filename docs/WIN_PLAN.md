# How to win

Grounded in PLE paper §3.2 (eq. 1, eq. 2), §5.2–§5.3, and the live competition
page. Written 16 Nov 2026. Deadline 5 Jan 2027 — roughly 50 days.

---

## 1. The insight everything else follows from

Equation 1: `s = 0.4·p + 0.6·G·O′`

Equation 2: `O′ = clip((O − O_naive) / (1 − O_naive), 0, 1)`, where `O = c_bound / c`

And the paper's own gloss on eq. 2:

> *"a naive design that fulfils all constraints earns no objective credit"*

Read those together and a specific, uncomfortable fact falls out:

| Design | Score |
|---|---|
| Infeasible (`G=0`) | `0.4·p` |
| **Compliant but no cheaper than the naive design** (`G=1, O′=0`) | **`0.4·p`** |

**A compliant, unoptimised design scores exactly the same as an infeasible one.**

Every failure-mode statistic in the paper points at compliance — 91% of
constraints pass, 41.3% of items clear the hard gate, 70.4% of zeros are
delivered-but-zero. That is where the field is looking. But `G` is only half of
the 0.6 term, and `G=1` on its own buys nothing. The other half, `O′`, pays only
for being **cheaper than the naive calibration design**.

So the field is optimising `G`. The score also pays for `O′`, and `O′` is a
continuous descent problem rather than a reasoning problem. That asymmetry is
the whole opportunity.

---

## 2. Two independent multipliers on the same 0.6

The 0.6 term is `G × O′`, so both factors pay the same rate:

```
Δs ≈ 0.6 · ( Δ(G-item clearance) × O′  +  G × ΔO′ )
```

Back-solving the paper's reported 50.6% with `p = 0.91` and item clearance
`0.413` implies the best configuration averages **`O′ ≈ 0.57`** on the items
where `G=1`. Two ways to move it:

| Lever | Current | Plausible target | Points |
|---|---|---|---|
| Item-level hard-constraint clearance | 41.3% | 50% | ≈ +3.0 |
| Cost efficiency `O′` | ≈ 0.57 | 0.70 | ≈ +3.2 |
| Both | | | **≈ +6** |

`50.6% → ~57%` would be first place by a wide margin, and it needs no better
model, no more tokens, and no prompt engineering.

---

## 3. The one architectural move: make the gate an optimiser, not a filter

Everyone building a code-gated harness uses gates to **reject**. That is the
entry fee now — five of ten visible notebooks are gate-based.

We use the same gates to do two jobs:

1. **Reject** — the agent may not finish while a hard constraint fails.
2. **Define the feasible region** — and then run a mechanical descent inside it.

```
generate deliverable
      │
      ▼
 gate layer  ──fail──▶ repair ──┐
      │                         │
     pass                       │
      ▼                         │
 cost model: evaluate O′        │
      │                         │
      ▼                         │
 propose a cheaper variant  ─────┘   (re-check every gate on the mutant)
      │  cheaper AND still feasible
      ▼
 accept, repeat to a fixed point
```

The descent is **search, not inference** — no model tokens. Tighten a conduit
one trade size, drop pump head by one increment, shave insulation thickness,
re-route a feeder — then re-run the *same deterministic gates*. Keep the mutant
only if `G` still passes and `O` improved. This is a constrained optimiser where
the constraint oracle already exists because we built it for the reject job.

**Why this is hard to copy in 50 days:** it requires a gate layer that is
complete enough to be trusted as a feasibility oracle. If your gates are
approximate, descending against them produces designs that pass your gates and
fail the grader. The cost of the strategy is *gate fidelity*, and that is the
one thing we have been building and testing since the start.

---

## 4. Gate fidelity is the thing that decides this

The dangerous failure mode is not "the gate rejects good work." It is:

> our gate says PASS, the official grader says 0.

That inverts the whole approach — a mis-calibrated oracle would drive the
descent confidently into infeasible territory.

**Therefore the first real experiment, before any optimisation work, is an
agreement study:** run the 29 public dev tasks, compare our gate verdict per
task against the published grader's verdict, and report the confusion matrix.

- Gate PASS + grader > 0 → true positive, the oracle is usable
- Gate PASS + grader 0 → **false positive, the oracle is dangerous**
- Gate FAIL + grader > 0 → false negative, we are throwing away points
- Gate FAIL + grader 0 → true negative, working as intended

False positives are the number to drive to zero before attempting `O′` descent.
This costs nothing — the dev graders are public — and it is exactly the kind of
controlled measurement Rubric criterion 1 (25 pts) rewards.

---

## 5. The 50-day plan

| Window | Goal | Done when |
|---|---|---|
| **Nov 17–23** | Contract compliance | `kit check` and `kit artifacts` green on the real skeleton; first valid commit |
| **Nov 24–30** | Gate fidelity study | Confusion matrix on 29 dev tasks; false-positive rate quantified |
| **Dec 1–7** | Item-level coverage on mechanical + electrical (41 of 56 hidden tasks); requirements-listing gate | Coverage measured per task |
| **Dec 8–14** | `O′` descent loop + all-or-nothing pre-checks (clash, every row served) | Descent improves `O` without breaking `G` on dev |
| **Dec 15–21** | Ablation, two models | Gate on/off delta and per-model table both real |
| **Dec 22–28** | Writeup + three figures | ≤2,000 words, headline finding at the top |
| **Dec 29–Jan 4** | Freeze, tag, submit SHA | One commit, SHA at top of writeup, nothing touched after |

**Two blockers that are yours, not mine:**
- Kaggle **identity verification** is required before you can submit.
- If the repo stays private, install the `ple-submission` GitHub App.

---

## 6. What we do not do

- **Do not chase prompt engineering.** Harness spread on Opus is 3.3 points and
  the median across all models is 3.0. The whole axis is smaller than one gate.
- **Do not buy score with tokens.** The eight most expensive configurations run
  $27–54/task and still score 33.8–49.3% — all below Opus at $17.18.
- **Do not start with structural.** 6 of 56 hidden tasks. Mechanical is 23 and
  the worst-scoring discipline (40.5%).
- **Do not trust one run.** Per-task range over three runs averages 15.4 points;
  105 of 595 task-harness cells span 30 or more.
- **Do not ship GLM 5.2.** 25.3% against Opus 50.6% — a 25-point concession in
  one config line.

---

## 7. Honest risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Gate false positives make the oracle unsafe | **Fatal to the thesis** | Fidelity study before any descent work |
| Contract never validated; submission ineligible | Fatal | Week 1 is compliance only |
| `O′` descent finds no legal cheaper variant | High | Cheap to test early; falls back to pure `G` gains |
| Coverage too narrow — gates silent on graded constraints | High | Measure coverage, publish it, don't hide it |
| Dev on Opus unaffordable (≈ $1,495 for 87 runs) | High | Ablate on Gemini 3.8 Flash (≈ $222), declare judge model |
| Gains measured on a 28% model don't transfer to a 50% model | High | State it plainly in the writeup; test two models |
| All-or-nothing civil/mechanical gates still zero tasks | Medium | Pre-submission clash and row-served checks |

---

## 8. The one-sentence version

Everyone else is building a better generator. We are building a better
*acceptance test* and then using it to run a cost descent the generator cannot
do — which attacks the half of the score that the field's own failure statistics
do not point at.
