# DD agent pilot — 18 November 2026

## Question

Can an agent with the DD checklists, the existing guidelines and read access
to the data room replace the `dd_checks` and `dd_priorities` pipeline? The
pipeline's checklist audits work, but its synthesis over large data rooms is
weak, because it only sees short findings.

## Setup

- Four startups with real Dealum data rooms of 3, 63, 109 and 150 documents,
  called A to D below. Startup names stay out of this repository.
- Model `gpt-6-luna` through OpenAI, for both the pipeline and the agent.
- For each startup: the pipeline once, the agent twice (to measure stability).
- A deal lead rated blind comparison packs. Each pack showed the pipeline's
  and the agent's priorities in one layout, as versions X and Y in random
  order, without the agent's `**Verified:**` lines.
- Run on a local machine on 17 November 2026.

## Results

| Data room | Documents | Same check status, pipeline and agent | Same check status, two agent runs | Agent runtime | Documents the agent opened | Agent tokens per run | Agent cost per run |
|---|---|---|---|---|---|---|---|
| A | 3 | 91% | 95% | 95–136 s | 3 | 0.4–0.5 M | $0.03 |
| B | 63 | 77% | 84% | about 176 s | 43–44 | 2.4 M | $0.09 |
| C | 109 | 68% | 81% | 175–225 s | 40–45 | 2.5–4.8 M | $0.10–0.12 |
| D | 150 | 71% | 71% | 185–192 s | 74–76 | 2.8–3.0 M | $0.10 |

The mean difference in importance (1–10) per check was 0.7–1.1 between the
pipeline and the agent, and 0.4–0.8 between two agent runs.

- **Rating:** the agent's priorities were the same or better in all four
  blind packs.
- **Cost:** the pipeline cost $0.36 for all four startups together, the agent
  $0.03–0.12 per run. 75–87% of the agent's input tokens came from the
  provider's prompt cache, which costs a tenth of normal input.
- **Runtime:** with OpenAI, the agent took 1.5–4 minutes per startup, the
  pipeline 1–3 minutes. One pipeline run took 23 minutes, because a single
  request hung until the 20-minute timeout. In an earlier test with a local
  model, the agent took 2 h 39 min against 57 min for the pipeline.
- **Reading:** the agent opened 40–75 documents in the larger data rooms. Its
  `**Verified:**` lines name what it checked, for example a dispute letter, the
  reply and whether the dispute is still open.
- **Product type:** for C, the pipeline chose software and the agent hardware,
  so they assessed different product checklists. This explains part of C's
  lower agreement.
- **Completeness:** every agent run recorded all checks without a follow-up
  turn.

### Stronger model for the synthesis only

`dd_priorities` with `gpt-6.1-sol` on the same findings chose the same five
topics as `gpt-6-luna` for all four startups, with a different order and
wording. A stronger model alone does not fix the synthesis; what it gets to see
is the limit.

`gpt-6.1-sol` was then dropped as too expensive: its pipeline cost $1.6–2.0
per startup. Its agent runs failed on the account's limit of 1 million tokens
per minute, because the checklist agents run in parallel.

### Total cost of the pilot

| Part | Cost |
|---|---|
| Agent with `gpt-6-luna` (8 runs) | $0.65 |
| Pipeline with `gpt-6-luna` | $0.36 |
| Pipeline with `gpt-6.1-sol` | $5.63 |
| Failed agent runs with `gpt-6.1-sol` | $2.70 |
| **Total** | **$9.34** |

## Decision

The agent's priorities are the same or better, and it costs about the same.
Its results are stable in small data rooms; in large ones this is still open
(see below). Following the decision rule of the pilot plan:

1. The agent becomes the default engine of `dd_checks` and writes the normal
   DD report, chapter audits and priorities. `dd_priorities` returns the
   agent's priorities. The pipeline stays as a fallback
   (`engine: "pipeline"` in `config/dd_checks/settings.json`) and `dd_checks`
   stops using it after a few weeks in production.
2. The data-room review of the web app (`dataroom_review`) uses the same
   pipeline and stays on it for now. Its server runs a local model with a
   context of 8,192 tokens, which is too small for the agent. It could move to
   the agent later, for example with a cloud model or a larger context. Until
   then, the pipeline code stays.
3. The agent's model calls wait for the shared scheduler, so parallel runs stay
   within `CLOUD_TPM_BUDGET`.
4. The other analytical skills are converted one at a time, each with a small
   blind comparison like this one: first `sha_review` and `cla_review`, then
   the skills that search the documents.
5. Qdrant, chunking and the checklist engine are removed once no skill uses
   them.

## Open points

- Two agent runs agree on only 71–81% of check statuses in the larger data
  rooms. The pipeline's own run-to-run agreement was not measured, so it is
  unknown whether this is worse than today.
- In large data rooms the agent opened 40–75 documents. It reached the others
  only through their names and the text search. The text search finds exact
  words, not meanings, so it can miss a document that uses other words or
  another language. The pipeline finds text by meaning, but gives the model
  only 25 short pieces per check. The blind rating showed no problem, but four
  startups are a small sample.
- With a local model instead of OpenAI, the agent would be about three times
  slower than the pipeline. This only matters if SICTIC-AI switches back to a
  local model.
