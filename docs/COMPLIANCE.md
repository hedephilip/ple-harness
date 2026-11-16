# Competition rules — what binds us

Read from the Official Competition Rules, 16 Nov 2026. Only the clauses that
change an engineering or strategic decision are listed; the rest is standard
Kaggle boilerplate.

---

## 1. The clause that changes the strategy

**C(7)(a):** *"Each Submission will be scored and/or ranked by the Evaluation
Rubric stated on the Competition Website. There will be no leaderboards for
Hackathon Competitions."*

**B(2):** *"Each team may submit one (1) submission only."*

No leaderboard, one submission, no score back until judging closes on 19 Jan
2027. There is **no external feedback signal at any point before the
competition ends.**

That elevates `scripts/gate_fidelity.py` from a nice-to-have to the entire
instrument panel. The dev set is the only place we will ever learn whether the
gate agrees with the grader. If we ship without that confusion matrix, we are
guessing once, blind, for $250,000.

It also hardens the freeze discipline in `WIN_PLAN.md`: after the final commit
there is no way to detect a regression, so nothing gets touched.

---

## 2. Competition Data — what we may never do

**B(4)(a):** data may be used *"only for participating in the Competition and on
Kaggle.com forums."*

**B(4)(b):** agree not to *"transmit, duplicate, publish, redistribute or
otherwise provide or make available the Competition Data to any party not
participating in the Competition."*

Consequences:

- **Never commit a task corpus.** No task folders, environment files, graders or
  reference deliverables in the repo. Only `artifacts/` as the competition
  requires, and only in the competition's own format.
- **The gate fixtures are clean.** Every test fixture in `tests/` is a
  hand-computed textbook value — 375 kip-ft, 5,000 m³, 137.46 mm. No Competition
  Data was used to build them, so the repo is publishable at close without a
  data-licensing problem. That was a quality choice; it turns out to be a
  compliance property.
- **The repo is private for two reasons now** — competitive and legal. Sharing
  Competition Data or derived corpora publicly would breach B(4)(b).

---

## 3. Code sharing is asymmetric — know which side you are on

**C(6)(a):** during the Competition Period you may not *"privately share source
or executable code developed in connection with or based upon the Competition
Data"*, including *"between separate Teams."* Public forum sharing is
permitted.

So:

| Action | Status |
|---|---|
| Private repo of our own code, one participant, no other team | Fine |
| Posting our approach in the Kaggle Discussion forum | Permitted — and it is public |
| DMing our harness to another team, or receiving theirs | **Breach** |
| Merging teams | Only through the official merger, before the deadline |

Practical rule: anything we say about this harness goes in public, or nowhere.
And given five of ten visible notebooks are already gate-based, public is not
where our edge should go before 5 Jan.

---

## 4. Licensing — the repo is half right

**B(5)(a):** *"Open Source License CC BY 4.0 (for the Writeup and documentation)
and Apache 2.0 or MIT License (for the agent harness and software code)."*

Current state:

- Harness code — `LICENSE` is Apache-2.0. Correct.
- **Documentation is not yet dual-licensed.** `README.md`, `docs/STRATEGY.md`,
  `docs/WIN_PLAN.md`, `docs/GATE_CONTRACT.md` and the writeup must carry CC BY
  4.0. A blanket Apache-2.0 file does not do this. Addressed below.

---

## 5. Reproducibility is an obligation, not a courtesy

**B(7)(a)(i):** the winner must deliver code that is *"capable of generating the
winning Submission"* and *"contain a description of resources required to build
and/or run the executable code successfully."*

This converts `kit check` from hygiene into a compliance gate. A repo that has
never executed cannot be shown to be capable of generating the submission. The
README now carries an explicit reproducibility section naming the environment,
the install step, the serve command and the eval command.

---

## 6. The rest, briefly

| Clause | Requirement | Our position |
|---|---|---|
| B(1)(a) | Team ≤ 5 | Solo |
| C(1) | 18+, not resident in sanctioned regions | Malaysia — eligible |
| C(5)(a) | One Kaggle account, no proxies | Single account |
| C(10) | W-8BEN / tax forms for foreign winners | Needed only on winning |
| B(6) | External data publicly accessible at no cost, or reasonable | We ship no external data; AISC/NEC enter only as published factors (φ = 0.90, 1.25 demand factor, K = 12.9), not as reproduced standard text |
| B(4) | Data access: competition use only | Enforced by `.gitignore` |

---

## 7. Status change on the competition page

An earlier snapshot showed *"This competition requires identity verification"*.
The current page shows *"You have accepted the rules for this competition."*
That suggests the acceptance step is done — worth confirming that identity
verification is also complete before relying on it, since it was listed as a
hard prerequisite for submitting.
