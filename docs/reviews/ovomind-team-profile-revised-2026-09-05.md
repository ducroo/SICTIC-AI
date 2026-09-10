# Ovomind: critique of the first revised team assessment

Reviewed 5 September 2026. This is a critique of the generated assessment, not an investment recommendation or an independent verification of Ovomind's claims.

**Verdict: the checklist architecture is useful, but this first output is not ready to send to a reviewer or founder.** It contains demonstrably false missing-evidence claims, incomplete person discovery, cached LinkedIn evidence outside the intended source scope, and a tendency to turn almost every answer into a large evidence request.

[Generated report](</Users/openclaw/SICTIC-AI/local-storage/storage/startups/ovomind/insights/team-profile-revised-ovomind-gpt-5-6-luna.md>). The original run and its audit artifacts have been preserved; no prompts or pipeline code were changed during this evaluation.

## Run and review scope

The live command was `python -m skills.team_profile_revised --dataset ovomind`, using the configured `openai/gpt-5.6-luna` model. Dataset sync initially hit the sandbox boundary; the authorised run outside the sandbox completed. All 40 checks completed without technical errors. The final report is 4,513 whitespace-delimited words.

| Category audit | Checks | Assessed | Insufficient information |
|---|---:|---:|---:|
| [1 Individual Founder Quality](</Users/openclaw/SICTIC-AI/local-storage/storage/startups/ovomind/insights/batch-audit/team-profile-revised-1-individual-founder-quality-gpt-5-6-luna.json>) | 14 | 5 | 9 |
| [2 Founding-Team Strength](</Users/openclaw/SICTIC-AI/local-storage/storage/startups/ovomind/insights/batch-audit/team-profile-revised-2-founding-team-strength-gpt-5-6-luna.json>) | 10 | 1 | 9 |
| [3 Governance and Extended Support](</Users/openclaw/SICTIC-AI/local-storage/storage/startups/ovomind/insights/batch-audit/team-profile-revised-3-governance-and-extended-support-gpt-5-6-luna.json>) | 10 | 2 | 8 |
| [4 Evidence Credibility and Verifiability](</Users/openclaw/SICTIC-AI/local-storage/storage/startups/ovomind/insights/batch-audit/team-profile-revised-4-evidence-credibility-and-verifiability-gpt-5-6-luna.json>) | 6 | 0 | 6 |

There are no Not applicable results at the top-level check status. That is not inherently wrong because several checks combine applicable and inapplicable subtopics. Across the checks, there are 191 proposed next-step entries before synthesis; the final report condenses these into 11 broad request bundles.

I reviewed the report and audit findings, compared selected claims against the full parsed team note and Yann's employment contract, and inspected the generated person roster and profiles. This is targeted source QA, not an exhaustive verification of every citation or every missing-document claim.

## What works

- The report treats Yann Frachi and Julien Masse as the two active founders and discusses employees and advisors separately. This is more coherent than the earlier report's individual headings, which applied founder labels to some people based on outside roles or executive titles.
- It identifies a useful division between Yann's commercial/company-leadership responsibilities and Julien's engineering/supplier background, with evidence references and individual limitations.
- It avoids numerical scores and treats company-reported licence/POC results separately from independently substantiated outcomes in most passages.
- It exposes execution, governance, incentive-plan and corroboration topics that a single team-strength score concealed. The saved JSON enables tracing a summary statement back to its originating check.
- The revised person profile correctly distinguishes Yann's doctoral candidacy from a confirmed awarded PhD; the older report overstated this credential.

## 1. False missing-evidence claims are the main reliability problem

**Yann's full-time start date.** N004 says the evidence does not establish when Yann became full-time and incorrectly says the team note does not identify its three full-time people. The final report repeats the missing-start-date claim and asks for the information again. Yet [his contract](</Users/openclaw/SICTIC-AI/docling_data/datasets2md/startups/ovomind/datasets/data-room_2026_08/2. Team & Advisors/2.1 Founders & Management/Yann Frachi (CEO)/Contrat travail - M. Frachi signé.pdf.md>) states 1 January 2022, 40 hours per week and 100% employment. The [team note](</Users/openclaw/SICTIC-AI/docling_data/datasets2md/startups/ovomind/datasets/data-room_2026_08/2. Team & Advisors/OVOMIND_Team_and_Advisors_4Sep2026_1.pdf.md:33>) explicitly identifies Yann, Julien and Takuya as full-time; its summary table repeats their names. R004 also incorrectly says Yann's working time is not documented, despite citing his contract. A responsible answer would establish at least the contracted full-time start in January 2022, distinguish the company's broader FTE-since-2019 claim, and leave continuity or earlier workload uncertain where appropriate.

**Arcanys' supplier role.** Q124/Q138 and the [final report](</Users/openclaw/SICTIC-AI/local-storage/storage/startups/ovomind/insights/team-profile-revised-ovomind-gpt-5-6-luna.md:67>) say the records do not establish whether Arcanys was a supplier or contractor. The [team note, section 7](</Users/openclaw/SICTIC-AI/docling_data/datasets2md/startups/ovomind/datasets/data-room_2026_08/2. Team & Advisors/OVOMIND_Team_and_Advisors_4Sep2026_1.pdf.md:79>), explicitly describes Arcanys as the outsourced engineering firm and shareholder, the systems it built, its engagement dates, the July 2026 termination and transfer of repositories and credentials. Whether either founder personally owns an interest in Arcanys remains a separate unknown; the supplier relationship does not.

These are workflow errors, not evidence gaps attributable to the startup. A missing-evidence statement must distinguish "not found in this retrieval" from "not present in the supplied dossier." Before proposing a document request, resolve named documents against the inventory, inspect the relevant full document and reconcile the claim with other completed checks.

## 2. Person discovery is incomplete and duplicates identities

The [discovery artifact](</Users/openclaw/SICTIC-AI/local-storage/storage/startups/ovomind/insights/persons-in-dataset/data-room-gpt-5-6-luna.json>) lists 17 names and generated 16 profiles after existing name matching. It contains both Chad Boulay and Chadwick Boulay; the generated Chad profile itself explains that the documents appear to refer to the same person. The raw roster also contains both Guillaume Channel and Guillaume Chanel, although existing matching reduced that pair before profile generation.

The roster omits eight people explicitly named in the current 18-person team note: Takuya Takahashi, Taichirou Musashi, Shun Harashima, Pravish Sainath, Mike Ambinder, Sylvain Haudegond, Claes Gartner and David Farez. Some of those people are recovered by later per-question retrieval, including the CTO, so they are not wholly absent from the final assessment. However, the promised shared profiles for all related persons were not actually assembled.

Discovery should start with complete identified team/organisation documents, reconcile aliases with documentary support, then supplement the roster with additional related people from the wider dossier. It needs a coverage check against explicit team lists; a successful JSON response alone is not adequate validation.

## 3. The source restriction is not enforced end to end

Five checks cite `linkedin/` files: N001/Q026/Q028, Q016/Q027, Q019/Q020, Q123/Q125/Q127/Q133, and Q134/R005. The final report explicitly cites `linkedin/julien-masse.json` and `linkedin/kenjimatsubara.json`.

The new person-profile branch skipped fresh public enrichment, but per-question semantic retrieval still accessed previously indexed LinkedIn content. This is cached public-source reuse, not evidence that this run performed a new public search. It nevertheless does not meet a strict data-room-only evidence boundary.

Apply the source restriction to discovery, dependency generation, per-check retrieval and cache provenance. Otherwise changing only the person-profile flag cannot guarantee the intended evidence scope.

## 4. Founder focus is being confused with founder-only functional coverage

N005 marks technical execution Partially covered partly because the current CTO and SDK developer are not founders. The [summary](</Users/openclaw/SICTIC-AI/local-storage/storage/startups/ovomind/insights/team-profile-revised-ovomind-gpt-5-6-luna.md:31>) also treats execution not being founder-led as a limitation.

That is an assessment-design choice, not a factual conclusion established by the dossier. A substantive CTO employee can own a function; this is different from relying on an occasional advisor. A founder-focused report should distinguish founder accountability, operating owner, demonstrated capability, available capacity and dependency risk. It should not automatically discount responsible delegation merely because the operator is not a co-founder.

This run provides a concrete answer to the unresolved larger-team question: **keep individual trait assessment focused on founders, but assess functional coverage across active management and employees, explicitly separating operating staff from advisors.** The handover from Arcanys to the internal Tokyo team is a meaningful execution topic; whether the CTO holds the founder label is not the useful discriminator.

## 5. The output is too long and too oriented toward requesting more evidence

Thirty-two of forty checks are Insufficient information. This is not a team-quality score or an 80% failure rate. Still, the combined design makes it easy for one missing subpart to turn a substantially answered topic into a broad unresolved finding.

For example, Q005 establishes relevant founder capability but adds five follow-ups spanning patent verification, product validation, time allocation, engineering milestones and PhD completion—several belong to other checks. Q025 establishes non-corporate entrepreneurial experience yet requests historical runway, resources and outcome attribution. Q016/Q027 recognises roughly seven years working together but largely presents the lack of pre-Ovomind history as an unresolved issue.

The 4,513-word final report repeats credential, commercial-verification and role-chronology caveats across categories. Its 11 follow-up bundles contain many distinct document requests, and known-present evidence is requested again. This is an internal audit working paper, not yet a useful concise synthesis.

Keep detailed checks in the JSON or an appendix. Aim initially for a 600–900-word category synthesis and about 5–8 prioritised follow-ups. Record what is established before listing residual uncertainty, avoid demanding independent proof for every ordinary biography fact, and distinguish investor-critical questions from optional corroboration.

## 6. Citation traceability needs deterministic checks

Some audit source paths do not resolve as written. For example, Q005 places Julien's IP assignment inside his personal subfolder, but the actual file is directly under `2.1 Founders & Management`. N003 and N005 contain similar extra-folder errors. Q137 includes a duplicated `2. Team & Advisors` directory in a CV citation.

The final synthesis further shortens many exact paths to basenames or generic labels such as "founder IP assignments." The relevant documents often exist, so these are not necessarily fabricated underlying sources; they are inaccurate references that hinder verification.

Use stable document identifiers and validated paths from retrieved metadata, with page references maintained separately. Validate citations after both audit and synthesis instead of relying only on prompt instructions.

## Recommended next iteration

1. Fix source filtering and verify supposedly missing evidence against named full documents. Use the Yann contract and Arcanys examples as regression cases.
2. Make person discovery complete against the team note and reconcile aliases before generating profiles.
3. Separate founder assessment from operating-team coverage so CTO employment is not treated like advisory support.
4. Validate citation paths and reconcile contradictory findings across checks before synthesis.
5. Shorten and prioritise the final synthesis, then rerun Ovomind against this preserved baseline.

The useful substantive thread is the founders' complementary experience, the transition to internal Tokyo software delivery, evidence behind the reported enterprise sales, and formalisation of current responsibilities and incentive arrangements. The current report makes those topics harder to see by mixing them with false gaps and an excessive verification checklist.
