# Cap table & convertible loan analysis (issue #17)

Two skills give reviewers a structured first-pass on a startup's ownership
and outstanding Convertible Loan Agreements (CLAs):

- **`captable_build`** extracts and validates the facts from a startup's
  data room and stores a versioned snapshot.
- **`captable_analysis`** computes conversion scenarios, applies a red-flag
  rubric, and writes a short narrative over the computed numbers.

The goal is not to replace legal or financial diligence: outputs highlight
what is present, what is missing, and what needs expert follow-up.

## Division of labor (the core design rule)

The LLM **finds, classifies, and extracts** values — always with a verbatim
source quote that is machine-verified against the parsed document text.
**Every calculation and consistency judgment is plain Python**: validation
checks, conversion mathematics, dilution, thresholds. No number a reviewer
relies on is ever LLM-computed.

## Pipeline (`captable_build`, stages 1–7)

```
data room ──1 classify──2 extract CLAs──3 assess──4 aggregate──┐
              │                                                │
              └─5 extract cap tables / register / pools──6 validate──7 snapshot
```

1. **Classify** every parsed document into 15 classes (current cap table vs
   forecast/scenario model, executed CLA vs term sheet, share register,
   articles, ESOP/PSOP plan, tax ruling, …). Runs in parallel chunks of 8
   documents (a Gemini structured-output limit).
2. **Extract CLA terms** per document against a SECA-derived schema:
   lenders (multi-lender agreements supported, per-lender amounts
   apportioned from the total when unstated — disclosed), principal,
   interest (mode, rate, day-count, compounding), maturity, conversion
   triggers (QEFR with minimum raise, change of control incl. repayment
   multiple, maturity), cap / discount / floor, denominator basis,
   subordination and its scope, MFN, pro-rata rights, conversion capital
   sources, consents, SHA accession. Every value carries a verified quote;
   absent terms land in `missing_terms` with the sections scanned.
3. **Assess** each CLA deterministically against configurable
   market-standard bands (`config/captable/assessment_rules.json`):
   discount inside/outside the 5–30% band, above the 33.33% tax
   reclassification threshold (verify with counsel — the threshold is
   config, not code), subordination scope (`principal_only` = severe),
   missing cap or maturity, conversion-capital enforceability, interest
   above the safe-harbor reference. Three states per item plus a severity.
4. **Aggregate** across CLAs: identical-terms grouping (dates/currency
   normalized) for the 10/20 non-bank withholding-tax rules — a lender
   counts once (fuzzy name identity: "Anna Beispiel" ≡ "Anna Barbara Beispiel") while
   each loan counts toward outstanding principal; term sheets are
   superseded by executed CLAs of the same lender with amount discrepancies
   emitted as questions; expired maturities are flagged
   "expired — check for conversion documents", never silently treated as
   fine; execution claims are corroborated against e-signature markers in
   the raw PDF streams (non-PDF sources are `not_applicable`, not
   failures).
5. **Extract** every cap-table version (group-aware holder rows,
   treasury/pool semantics, row-completeness enforced against the table's
   own totals), the share register (current holdings anchored on the
   participation column), and ESOP/PSOP pool overviews.
6. **Validate in code**: per-class issued totals; the diluted equation
   (diluted = issued − treasury + option/pool deltas); a holder-level
   diluted row-sum; register reconciliation **against the cap-table version
   nearest the register's own date** (cross-dated comparisons are
   downgraded and disclosed, since a difference may be a legitimate
   transfer in between); pool cross-document consistency (paired by pool
   identity, one-sided coverage tolerated); nominal-value floor
   (art. 624 CO); CLA-lender-is-shareholder lifecycle checks; and
   cross-snapshot consistency (shrinking classes/holders without evidenced
   events).
7. **Snapshot**: `insights/captable/snapshots/<as_of>.json` (one per
   evidenced state, all kept), `latest.json` (never overwritten by an
   older rebuild), a table-only `captable.md`, and a visual one-pager
   `captable.html` rendered deterministically from the snapshot (see
   below). As-of dates are normalized to ISO in code; unparseable date
   strings never win.

## Analysis (`captable_analysis`)

Reads a snapshot and computes, in pure Python
(`lib/captable/model.py`): loan balances accrued under four day-count
conventions with simple/annual compounding; SECA-style conversion pricing
(lower of cap-derived and discounted price, floors, nominal warnings); and
a hypothetical round converted under **all three market methods side by
side** — pre-money, percentage-ownership (fixed-point solver for the
circularity), dollars-invested — because CLAs rarely fix the method and the
choice can move founder ownership by several points. Adds the CHF 1M
stamp-duty exemption tracking, per-scenario `founders_post_round_pct`, and
the handbook red-flag rubric (scoped to the snapshot date). The LLM writes
a narrative constrained to the computed JSON.

## Visual one-pager (`captable_analysis render`)

The division-of-labor rule extends to the last mile: the HTML page a
reviewer actually looks at is rendered **in pure Python from the stored
snapshot** — no LLM ever re-types a number into the visual. Every build
writes `insights/captable/captable.html`; `render` re-renders on demand
(and includes the conversion-scenario table when the stored analysis was
computed over the same snapshot state). Ownership percentages use the
same denominator as the rubric, so chart and analysis can never disagree.
Ad-hoc visual exploration in a chat client stays fine — but the standard
deliverable is this deterministic page.

## Semantics contracts worth knowing

- **`missing_terms`**: for presence-type booleans, `false` is an
  evidence-backed absence claim — it appears in `missing_terms` with the
  sections scanned. Conclusion and evidence, not a contradiction.
- **Quotes** are matched against an alphanumeric projection of the parsed
  text (robust to OCR spacing, markdown table pipes, and model ellipses —
  each ellipsis-separated fragment must verify).
- **Snapshots** are versioned by evidence date, not by generating model —
  a deliberate deviation from the `InsightFile` convention, which the
  model-dependent analysis narrative does use.

## Usage

```bash
python -m skills.captable_build build --dataset <startup> [--fresh]
python -m skills.captable_analysis run --dataset <startup> \
    [--as-of DATE] [--pre-money N] [--investment N]
python -m skills.captable_analysis render --dataset <startup> [--as-of DATE]
```

Stage-by-stage commands and details: `skills/captable_build/SKILL.md` and
`skills/captable_analysis/SKILL.md`.

## Testing & development cost

`tests/fixtures/captable/` is a synthetic data room ("Fixture Robotics
AG") with a ground-truth answer key, two dated cap-table versions (for the
cross-snapshot checks), deliberately absent CLA terms (for the
missing-terms recall property), and a planted share-transfer anomaly.
A full pipeline smoke run against it on
`--model gemini/gemini-3.5-flash-lite` costs about one cent; a real data
room on the default model costs roughly CHF 0.5–1.5 once (work products
are cached; only `--fresh` re-runs the LLM stages). Lite-model output is
measurably worse — never use the override for real due-diligence output.

## Known limitations / follow-ups

- The 33.33% discount reclassification threshold and the
  newly-issued-vs-treasury-shares point are **unverified with tax
  counsel** (both live in config/prompts, not code).
- Anti-dilution provisions are extracted but not yet modelled; exit
  waterfalls (incl. phantom-share liabilities) are stored but not
  computed.
- Syndicate members are not resolved (the 10/20 outputs say so rather
  than reporting a false pass).
- Conversion notices are classified but not yet read to flip a CLA's
  status to `converted`; similarly, the register's transfer/acquisition
  entries are not yet mined as evidence for cross-version share movements
  (a documented transfer could resolve a `shrinking_holder` warning).
- Classification confidence varies slightly across runs (LLM-judged);
  classes have been stable in testing, and an eval suite over the fixture
  answer key is the planned guardrail.
