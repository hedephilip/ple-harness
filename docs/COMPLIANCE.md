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
- **The repo is public, and that is the compliant way to give access.**
  C(5)(d): *"No private sharing outside of Teams. Privately sharing code or
  data outside of Teams is not permitted. It's okay to share code if made
  available to all Participants on the forums."* Adding a judge or an
  organizer as a private collaborator would be private sharing outside a
  Team; a public repository is not private sharing, and B(5)(a) requires an
  open-source licence for the winning harness anyway. The binding constraint
  is therefore not visibility but content: B(4)(b) forbids publishing
  Competition Data, so the repo stays public and the data stays out.

---

## 3. Code sharing is asymmetric — know which side you are on

**C(6)(a):** during the Competition Period you may not *"privately share source
or executable code developed in connection with or based upon the Competition
Data"*, including *"between separate Teams."* Public forum sharing is
permitted.

So:

| Action | Status |
|---|---|
| Public repo of our own code (no Competition Data) | **Permitted — this is the current state** |
| Adding a judge or organizer as a private collaborator on a private repo | **Breach of C(5)(d)** |
| Posting our approach in the Kaggle Discussion forum | Permitted — and it is public |
| DMing our harness to another team, or receiving theirs | **Breach** |
| Merging teams | Only through the official merger, before the deadline |

Practical rule: anything we say about this harness goes in public, or nowhere.
That is now literal — the repository is public — so treat every commit as
read by a judge and by competing teams.

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
| B(2) | One submission per team | One entry |
| C(7)(a) | *"There will be no leaderboards for Hackathon Competitions."* Judged on the Evaluation Rubric published on the site | Confirms the writeup is the scored artefact, not a hidden-test mean |
| B(5)(a) | Winning licence: Apache 2.0/MIT for code, CC BY 4.0 for writeup and docs | `LICENSE` is Apache-2.0; docs and writeup carry CC BY 4.0 |
| B(7)(a)(i) | Code must be capable of generating the winning submission, with resources described | README `Reproducibility` table |

---

## 7. Status change on the competition page

An earlier snapshot showed *"This competition requires identity verification"*.
The current page shows *"You have accepted the rules for this competition."*
That suggests the acceptance step is done — worth confirming that identity
verification is also complete before relying on it, since it was listed as a
hard prerequisite for submitting.

---

## 8. One unresolved contradiction between two official documents

The Kaggle overview says:

> *"Switching model_api in submission.yaml to your target google-cloud/<id> model
> before committing (after generating artifacts/ on a local or personal API
> model) will not disqualify you."*

The PLE repository's `docs/rules.md` says:

> *"Your committed artifacts/ must be exported by eval/run.py from the harness
> you submit, running the model_api declared in submission.yaml."*

These cannot both be true. The first permits generating artifacts on a cheap
model and switching; the second requires the declared model to have produced
them.

**This is a cost question with an unmeasured answer.** The paper reports $17.18
per task for Opus in Claude Code (Table 3), so 29 dev tasks cost roughly $500
per pass at that rate — arithmetic on a published figure, not a quote, and
not a prediction for this harness.

Do not resolve it by assumption. Ask on the Kaggle Discussion forum — public
posting is explicitly permitted by C(6)(a) — and keep the answer. Until then,
plan for the expensive path in the budget and the cheap path in the schedule.
