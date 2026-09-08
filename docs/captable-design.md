# Cap table & CLA skills — design rationale and Swiss background

Companion to [captable.md](captable.md) (which describes what the
pipeline does). This document records **why** it is built that way: the
Swiss legal and tax rules baked into the checks, the market knowledge
behind the extraction schema, and the design decisions with their
reasoning. Sources: the SECA CLA model documentation (Feb 2025), the
Swiss Angel Investor Handbook (ch. 7, 8.3–8.4), published conversion-math
worked examples, and the CUAD/ContractEval contract-extraction
benchmarks.

## Anatomy of a Swiss CLA (SECA model — the extraction ground truth)

The SECA convertible loan documentation (short + long form) is the
de-facto Swiss standard; corpus documents may follow either or neither.
The extraction schema mirrors its data core:

| Term | Why it is extracted this way |
|---|---|
| Principal + currency | Loan currency may differ from round currency → SNB rate at subscription date (SECA rule). |
| Interest | interest-free / fixed / capped at the ESTV safe-harbor rate; the safe-harbor rate itself is extracted when the contract quantifies it, since the analysis must accrue at the LOWER of ceiling and safe-harbor. Day-count convention and compounding change the Loan Balance materially on older notes. |
| Maturity | typically 9–36 months; **no maturity date at all is an investor red flag**. |
| Conversion triggers | Qualified Equity Financing Round (QEFR, with a total minimum AND often a separate new-investor minimum — without the latter, insiders alone can trigger mandatory conversion), Change of Control (incl. repayment-multiple options), Maturity. Mandatory vs voluntary is negotiated per case. |
| Conversion price | **defined per trigger**: round conversions usually price at the lower of cap-derived and discounted round price (discounts may be time-stepped); maturity (and sometimes CoC) conversion frequently uses a FIXED per-share price instead. Missing the fixed price mis-prices exactly the scenario that governs an expired loan. |
| Cap / floor / discount | cap common but not mandatory; floor rare at seed. Discounts: SECA 5–30% typical; market data 15–25% most common. |
| Denominator basis | issued-and-outstanding (founder-friendly) vs fully-diluted (investor-friendly) — negotiated, never assumed. |
| Subordination | art. 725b para 4 no. 1 CO wording; SECA subordinates the full "Loan Balance owed now or in the future" (principal + interest). **Non-subordinated is a red flag; principal-only subordination is a severe defect** (accrued interest stays senior — the company can remain technically over-indebted). |
| Shareholder consents | SECA Annex 2 declarations (waiver of subscription rights, vote for the capital increase); missing consents = enforceability risk. |
| SHA accession | condition precedent to conversion. |
| Execution evidence | execution date + signatures. An unsigned CLA in a data room is effectively a term sheet: it is demoted and drops out of outstanding-principal totals. |
| Disclosure duty | art. 634a para 3 / art. 652c CO (since 2023): conversion discloses subscriber identity and amounts in the articles and commercial register. |

## The term checklist (team-editable, completeness lives in config)

Following the repo pattern — what a skill looks for lives in **config**,
like the `config/dd_checks/checklists/*.md` and
`config/sha_review/checklists/*.md` files that drive those skills — the
CLA term list is itself an editable checklist:
**`config/captable/cla_terms.md`**. Each `### field (type)` entry there
becomes one field of the extraction schema, its body text becomes the
model guidance for that term, and every value field carries a
machine-verified verbatim quote. **Adding a term or refining guidance is
a config edit — no code change** (the schema, the prompt, quote
verification, and missing_terms handling all follow the checklist
automatically). The assessment bands live in `assessment_rules.json`.

The one guarded exception: fields the pipeline **computes on** —
removing or re-typing them in the checklist would silently zero out
downstream numbers, so `lib/captable/cla_terms.py` fails loudly at load
time instead (`CODE_CONSUMED_FIELDS`). That core is: `lenders`,
`status`, `missing_terms` (structural shapes owned by code);
`execution_date`, `signatures_complete`, `principal_total`,
`principal_currency`, `maturity_date` and the numbers
`interest_rate_pct`, `interest_safe_harbor_rate_pct`, `qefr_min_raise`,
`qefr_min_new_money`, `coc_repayment_multiple`,
`maturity_conversion_price`, `valuation_cap`, `discount_pct`,
`valuation_floor`; the enums `interest_mode`, `interest_day_count`,
`interest_compounding`, `denominator_basis`, `subordination_scope`,
`conversion_capital_sources`; and the booleans `qefr_present`,
`coc_present`, `maturity_conversion_present`, `subordinated`,
`mfn_clause`, `pro_rata_rights`, `shareholder_consents_referenced`,
`sha_accession_required`. A unit test pins this list to the code.

**Deterministic assessment items (12)** over those fields
(`lib/captable/assessment.py`, bands in `assessment_rules.json`):
`discount`, `interest_rate`, `qefr_trigger`, `change_of_control`,
`maturity_date`, `valuation_cap`, `denominator_basis`, `subordination`,
`conversion_capital`, `mfn_clause`, `pro_rata_rights`, `sha_accession` —
three states each (standard / deviating / absent) plus a severity.

**Cap-table / register / pool extraction** (own schemas in the same
config folder): `as_of_date`, `share_classes` (id, name, nominal value,
votes), `stakeholders` (name, group, kind, role, holdings by class,
diluted count, invested amount), `pools` (kind, label, total, granted,
unallocated), `totals` (by class + diluted), `fully_diluted_definition`,
`assumptions`; the register anchors current holdings, the pool overview
feeds cross-document consistency.

## Handbook-derived heuristics behind the rubric and checks

1. **"Fully diluted" is ambiguous** (full pools vs granted-only vs
   granted-ESOP + vested-PSOP). The pipeline records which definition a
   source uses and flags when it is unstated — clarify before
   negotiating a fully-diluted pre-money.
2. **Economic vs voting ownership diverge** — PSOP/phantom rights dilute
   exit proceeds but not votes.
3. **ESOP/PSOP often live in side agreements**, absent from the share
   register; a cap table without a pool line deserves a diligence
   question, not silence.
4. **Convertible conversion is a range, not a number** — hence the
   scenario engine, never a single point estimate.
5. **Dead equity**: departed holders >10% fully diluted is the
   handbook's threshold.
6. **Founder majority pre-Series A**: founders below 50% = "big and
   costly mistakes have been made"; investors at more than twice the
   founders = "giant red flag".
7. **10/20 non-bank rules**: more than 10 lenders on identical terms (or
   more than 20 overall) re-qualifies the loans as bonds → 35%
   withholding on interest. Counting lenders per identical-terms group
   ACROSS documents is a cross-document check no per-document review can
   do — and sub-participants count, so with unresolved syndicate
   membership the output must say "composition undisclosed — verify",
   never a false pass.
8. **CLA holders have no statutory information rights** until conversion
   — contractual reporting duties are an assessment point.

## Swiss corporate-law and tax rules baked into the pipeline

- **Nominal-value floor (art. 624 CO)**: shares cannot be issued below
  nominal value. A cap/discount-implied conversion price below nominal
  is legally impossible → validation finding, never a silent clamp.
- **Discount above 33.33%** reportedly reclassifies the CLA as
  "non-classic" (discount portion income-taxable, withholding
  complications). **Threshold unverified with tax counsel** — it lives
  in `config/captable/assessment_rules.json`, not code, so it can be
  corrected without a release. A second **verify-with-counsel** item:
  the claimed tax requirement that conversion shares be newly issued
  rather than treasury shares — recorded here, not enforced anywhere.
- **1% issuance stamp duty (Emissionsabgabe)** above the one-time
  CHF 1M exemption: CLA conversions count as contributions and often
  push a startup over the threshold together with the priced round. The
  analysis tracks cumulative paid-in capital against the exemption and
  reports the cash impact.
- **Conditional capital — with a SECA correction**: startup CLAs are
  *usually not* funded via conditional/authorized capital (the
  conversion-share class is unknown in advance) — hence the Annex 2
  consent mechanism. The extraction records which mechanisms a CLA
  relies on (`consents` / `conditional_capital` / `kapitalband`, the
  latter being the post-2023 capital band of art. 653s ff. CO) and the
  assessment flags a CLA with no enforceable path to conversion shares;
  comparing conversion volume against the articles' actual capital
  headroom is a documented follow-up, not yet computed.
- **Phantom shares are three constructs, not one**: (a) legal share
  counts (register — phantom excluded), (b) economic dilution view
  (phantom included for proceeds %), (c) exit-waterfall cash liability.
  v1 records pool lines (incl. PSOP) as the sources state them; the
  three-construct separation is the modelling target and phantom-aware
  economic views and waterfalls are deferred. The standing rule either
  way: phantom rights are excluded from conversion-price denominators
  unless the CLA's own fully-diluted definition says otherwise — never
  let phantom inflate the pre-money share count.
- **Cantonal ESOP/PSOP tax ruling** ("the Swiss 409A"): employee equity
  without a binding ruling exposes employees to unpredictable income tax
  at exit. Tax rulings are classified when present in the data room; the
  automatic pool-without-ruling diligence question is a follow-up.
- **Lender domicile** is extracted per lender (domestic vs foreign
  withholding treatment differs) as input for the tax follow-up; the
  computed 10/20 outputs do not yet use it.

## Conversion mathematics (why `lib/captable/model.py` exists)

No open-source implementation covers Swiss CLA conversion math (the OCF
ecosystem — PyOCF, OCX — is US-centric and event-sourced), so the model
is ours, validated against published worked examples.

- **Circularity is inherent**: the conversion price depends on the share
  count, which depends on the converted shares — solved with a
  fixed-point solver (also covers the pre-money-pool double
  circularity).
- **Three market methods** for converting notes in a priced round —
  pre-money / percentage-ownership / dollars-invested — can move founder
  ownership by several points on identical inputs, and CLAs are usually
  silent on the method. The engine computes **all three side by side**
  and never silently picks one. This is the single most important
  honesty property of the scenario output.
- **Day-count conventions** (act/365, act/360, act/act, 30/360) and
  simple-vs-compound accrual change the Loan Balance; unstated
  conventions fall back to act/365 simple, always recorded as an
  assumption.
- **SECA rounding**: fractional conversion shares round down with the
  remainder waived — reconciliation tolerances are per-lender, not
  aggregate.

## Design decisions and their reasons

- **Division of labor (the core rule)**: the LLM finds, classifies, and
  extracts values — every value with a machine-verified verbatim quote
  (the hallucination guard). All arithmetic and consistency judgment is
  plain Python. No number a reviewer relies on is ever LLM-computed;
  the HTML renderer extends this to the last mile.
- **Anti-laziness evidence contract** (the CUAD/ContractEval lesson —
  the dominant LLM contract-extraction failure is falsely answering "no
  such clause"): absence claims are only accepted with evidence. A
  presence-boolean `false` states the conclusion; the `missing_terms`
  entry carries the sections scanned as its evidence. The synthetic
  fixture keeps two deliberately absent terms as a recall check.
- **OCF-inspired snapshot, not full OCF**: event-sourcing
  (issuances/transfers as event streams) is right for systems of record
  and too heavy for first-pass DD. The snapshot keeps OCF *vocabulary*
  (stakeholders, classes, convertibles, triggers) for a later migration
  path, and the cross-snapshot checks provide event-style validation
  without event sourcing (share counts only grow unless a
  split/cancellation is evidenced; shrinking holders need a documented
  transfer).
- **Versioning**: document versions (same state, multiple files — latest
  wins, others superseded) are distinct from cap-table states over time
  (each its own dated snapshot, all kept forever). Snapshots are
  versioned by evidence date, not by generating model — a deliberate
  deviation from the `InsightFile` convention, which the model-dependent
  analysis narrative does use.
- **Term sheets are excluded from outstanding totals** — extracted and
  kept distinct, superseded by executed CLAs of the same lender, with
  amount discrepancies emitted as questions.
- **CLA lifecycle** (`executed | term_sheet | converted | repaid`):
  status changes require evidence; an old CLA in a recent data room may
  well have converted. A lender of an "executed" CLA who already appears
  as a shareholder triggers a neutral lifecycle question.
- **Syndicates v1**: detect presence (a syndicate/nominee lender) and
  make its consequences explicit — sub-participants count toward the
  10/20 limits, so the outputs say "composition undisclosed — verify"
  and emit a diligence question rather than reporting a false pass.
  Resolving individual membership, and assessing the syndicate's own
  rules (agreement in data room, voting arrangement, members-level
  drag-along), are follow-ups.
- **Classification is a mandatory stage**: real corpora contain forecast
  and scenario models masquerading as cap tables ("Forecast Cap Table
  Series A", "Dilution Calculator") — extracting one as *the* cap table
  is confident garbage.
- **Validation happens in code, not prompts**, and violations become
  structured findings, never silent corrections.

## Deliberately out of scope in v1

Anti-dilution provisions, phantom-share liabilities, and exit waterfalls
(neither extracted nor modelled yet); the capital-headroom comparison
against the articles; the pool-without-ruling diligence automation;
syndicate member resolution and syndicate-rules assessment; using lender
domicile in the computed tax outputs; conversion-notice reading to flip
lifecycle status; register transfer-entry mining; disclosure-schedule
mining for non-captable facts (dd_checks territory); and the accrual
value-date nuance — all recorded with the known limitations in
[captable.md](captable.md).
