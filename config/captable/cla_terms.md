# CLA extraction terms

This file is the checklist that drives the CLA extraction — edit it to
change WHAT the pipeline looks for, no code change needed (the same way
`config/dd_checks/checklists/` drives dd_checks). Every `###` entry
becomes one field of the extraction schema; its body text becomes the
guidance the model reads for that term. Edits apply on the next
extraction run (config is re-read on change); already-stored extractions
only pick up new terms after a fresh run.

Grammar: `### field_name (type)` — `field_name` is lowercase snake_case,
`type` is one of:

- `number`, `string`, `boolean` — a value with a mandatory verbatim
  source quote (null + a `missing_terms` entry when absent).
- `presence boolean` — a boolean whose `false` means "no such clause
  exists": an absence claim that no quote can prove, so it ALWAYS needs
  a `missing_terms` entry with the sections scanned.
- `enum: a | b | c` — one of the listed values. Members named
  `unstated`, `unclear`, or `not_subordinated` are recognized absence
  values and need no quote (but do need a `missing_terms` entry for
  `unstated`).
- `enum list: a | b | c` — zero or more of the listed values.
- `structural` — the field's shape is owned by the code
  (`cla_extraction_base_schema.json`); only the guidance is editable
  here.

`##` headings group the terms (documentation only). Fields the pipeline
computes on (aggregation, assessment, analysis) are guarded in
`lib/captable/cla_terms.py` — removing or re-typing one fails loudly at
load time; adding terms and refining guidance is always safe.

## Parties and lifecycle

### lenders (structural)

ALL lenders that are party to this agreement. Swiss CLAs come both as
single-lender agreements and as one multi-lender agreement listing every
investor; list each lender once with its own quote (the party block
naming it) and, when the document states per-lender loan amounts (often
in an annex table), its `principal_amount`.

### borrower_name (string)

The borrower — the startup company that is party to this agreement, as
named in the party block.

### status (structural)

`executed` only if the document shows completed execution (signature
blocks filled, signature markers, execution date present, or the text
states it is signed). Drafts, templates, and term sheets are
`term_sheet`. Only use `converted`/`repaid` if the document itself
states it.

### status_evidence (structural)

One sentence saying why you chose that status.

### execution_date (string)

The date the agreement was executed/signed, as stated in the document.

### signatures_complete (boolean)

True only if ALL parties appear to have signed; false if signature
blocks are visibly empty; null if the text does not let you tell
(common with OCR of signature pages — say so via missing_terms).

## Principal

### principal_total (number)

The aggregate nominal loan amount under THIS agreement (not a round
maximum). For a single-lender agreement this is that lender's amount.

### principal_currency (string)

The currency of the principal (e.g. CHF, EUR, USD).

## Interest

### interest_mode (enum: interest_free | fixed | safe_harbor_capped | unstated)

`interest_free` when the loan bears no interest; `fixed` for a plain
rate; `safe_harbor_capped` when tied to the Swiss federal tax
administration safe-harbor rate (e.g. "the LOWER of X% and the ESTV/SFTA
safe harbor rate").

### interest_rate_pct (number)

The stated interest rate as a percentage — for `safe_harbor_capped`
loans this is the stated ceiling (the X in "lower of X% and the safe
harbor rate").

### interest_safe_harbor_rate_pct (number)

For `safe_harbor_capped` loans: the safe-harbor rate ITSELF if the
document states it (contracts often quantify it in passing, e.g.
"currently 1.75%"); null when the document does not put a number on it.

### interest_day_count (enum: act/act | act/360 | act/365 | 30/360 | unstated)

Only if the text states the convention (e.g. "365-day year" = act/365,
"actual number of days elapsed ... 360" = act/360, "30/360" = 30/360).

### interest_compounding (enum: simple | compound_annual | compound_other | unstated)

Whether interest compounds. SECA's default is simple accrual on the
principal.

## Maturity and conversion triggers

### maturity_date (string)

The maturity date of the loan.

### qefr_present (presence boolean)

Is there a conversion trigger at a qualified equity financing round?

### qefr_min_raise (number)

The TOTAL minimum raise threshold that qualifies a round, in the loan
currency.

### qefr_min_new_money (number)

Qualified-round definitions often have TWO components — a total-round
minimum (`qefr_min_raise`) AND a minimum that must come from NEW
investors ("of which at least CHF X from new investors"). Report the
new-money component here; null only when the definition truly has a
single threshold. This matters: without a new-money component, insiders
alone could trigger the mandatory conversion.

### qefr_mandatory (boolean)

True for mandatory/automatic conversion at a qualified round, false for
voluntary/at-lender's-option.

### coc_present (presence boolean)

Is there a conversion (or repayment) trigger at a change of control?

### coc_mandatory (boolean)

True for mandatory/automatic conversion at a change of control, false
for voluntary/at-lender's-option.

### coc_repayment_multiple (number)

If, at a change of control, the lender may demand REPAYMENT at a
multiple of the principal instead of converting (e.g. "2.5x the
Principal Amount"), the multiple as a number (2.5); null when no such
option exists.

### maturity_conversion_present (presence boolean)

Is there a conversion trigger at or around the maturity date?

### maturity_conversion_mandatory (boolean)

True for mandatory/automatic conversion at maturity, false for
voluntary/at-lender's-option.

### maturity_conversion_price (number)

Conversion-price definitions frequently vary BY TRIGGER (read the full
"Conversion Price" definition including all lettered clauses and
annexes): discount/cap pricing may apply only to round conversions
while maturity (and sometimes CoC) conversion uses a FIXED per-share
price. Report that fixed maturity price here; if the maturity
conversion instead uses the discount/cap mechanics, null. A missed
fixed price silently mis-prices the exact scenario that applies to an
expired loan.

## Pricing

### valuation_cap (number)

The valuation cap as a CHF (or loan-currency) COMPANY VALUATION amount,
not a per-share price.

### discount_pct (number)

The discount as a percentage (e.g. 20 for "80% of the subscription
price"). If the discount changes over time, put the currently earliest
applicable rate here and describe the full schedule verbatim-ish in
`discount_schedule`.

### discount_schedule (string)

The full time-stepped discount schedule when the discount changes over
time (e.g. "15% within 4 months, 25% after"); null for a flat discount.

### valuation_floor (number)

A valuation floor as a company valuation amount, if any (rare at seed,
seen in bridge rounds).

### denominator_basis (enum: fully_diluted | issued_and_outstanding | unstated)

Whether cap/floor prices divide by fully-diluted shares or
issued-and-outstanding shares — negotiated, never assume.

## Protections and mechanics

### subordinated (boolean)

Is the loan subordinated (art. 725b CO wording or equivalent)?

### subordination_scope (enum: loan_balance_full | principal_only | unclear | not_subordinated)

`loan_balance_full` when subordination covers principal AND accrued
interest (e.g. the SECA "Loan Balance owed now or in the future"
wording); `principal_only` when only the principal is subordinated;
`unclear` when subordinated but the covered amount is ambiguous;
`not_subordinated` when there is no subordination.

### mfn_clause (presence boolean)

A most-favored-nation clause upgrading this lender to better terms
granted to later lenders.

### pro_rata_rights (presence boolean)

Participation rights of the lender in the future equity round beyond
the conversion itself.

### conversion_capital_sources (enum list: consents | conditional_capital | kapitalband)

ALL mechanisms the document contemplates for creating the conversion
shares — shareholder consent declarations (`consents`), conditional
capital (`conditional_capital`), a capital band (`kapitalband`). List
every one that appears; empty array when none is stated. The quote must
come from a clause that establishes or relies on the mechanism (an
undertaking, covenant, condition, or annex reference) — NOT from a
representations/warranties carve-out that merely mentions it.

### shareholder_consents_referenced (boolean)

Does the document reference shareholder consent/support declarations
for the conversion (annexed or to be obtained)?

### sha_accession_required (boolean)

Must the lender accede to the shareholders' agreement as a condition of
conversion?

### governing_law (string)

The governing law and forum, as stated.

## Evidence

### missing_terms (structural)

For every term reported as null/unstated — and every presence boolean
reported false — add an entry using the exact field name as `term` and
list in `sections_scanned` the concrete sections/headings/pages checked
before concluding the term is absent.
