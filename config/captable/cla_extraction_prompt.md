You are extracting the terms of ONE Swiss convertible loan agreement (CLA) or
convertible-loan term sheet for investor due diligence. You are given the full
parsed text of the document (converted from PDF; possibly OCR of a scan, so
minor character noise is expected; the text may be German, English, or
bilingual).

Extract every field of the response schema. The reference frame is the SECA
CLA model documentation (February 2025), but the document may deviate from it
in any way — report what THIS document actually says.

Evidence rules (strictly enforced; violations are rejected):

1. Every extracted value MUST carry a `quote`: a short verbatim snippet
   (roughly 5-30 words) copied from the document text that evidences the
   value. Copy the snippet exactly as it appears in the provided text,
   including OCR noise. Do not paraphrase, translate, or "clean up" quotes.
2. When a term is genuinely absent or unreadable, set its value to null (or
   the "unstated"/"unclear" enum member where the schema has one) and set the
   quote to null. NEVER guess a value.
3. For every term you report as null/unstated, add an entry to
   `missing_terms`. The same applies to every presence-type boolean
   (`qefr_present`, `coc_present`, `maturity_conversion_present`,
   `mfn_clause`, `pro_rata_rights`) you report as false — "no such clause
   exists" is an absence claim that a quote cannot prove — and to any other
   boolean reported false or null without a supporting quote. Use the exact schema field name as `term` (e.g.
   "valuation_cap", not "cap") and list in `sections_scanned` the concrete
   sections/headings/pages of the document you checked before concluding the
   term is absent. An empty `sections_scanned` is rejected. Being thorough
   here matters more than being fast: absence claims without scan evidence
   are the number-one failure mode of this task.

Field guidance:

- `status`: `executed` only if the document shows completed execution
  (signature blocks filled, signature markers, execution date present, or the
  text states it is signed). Drafts, templates, and term sheets are
  `term_sheet`. Only use `converted`/`repaid` if the document itself states
  it. `status_evidence`: one sentence saying why.
- `signatures_complete`: true only if ALL parties appear to have signed;
  false if signature blocks are visibly empty; null if the text does not let
  you tell (common with OCR of signature pages — say so via missing_terms).
- `lenders`: ALL lenders that are party to this agreement. Swiss CLAs come
  both as single-lender agreements and as one multi-lender agreement listing
  every investor; list each lender once with its own quote (the party block
  naming it) and, when the document states per-lender loan amounts (often in
  an annex table), its `principal_amount`.
- `principal_total`/`principal_currency`: the aggregate nominal loan amount
  under THIS agreement (not a round maximum). For a single-lender agreement
  this is that lender's amount.
- `interest_mode`: `interest_free` when the loan bears no interest; `fixed`
  for a plain rate; `safe_harbor_capped` when tied to the Swiss federal tax
  administration safe-harbor rate.
- `interest_day_count`: only if the text states the convention (e.g. "365-day
  year" = act/365, "actual number of days elapsed ... 360" = act/360,
  "30/360" = 30/360).
- Trigger fields: `qefr_*` = conversion at a qualified equity financing round
  (report the minimum raise threshold in the loan currency if given);
  `coc_*` = change of control; `maturity_conversion_*` = conversion at or
  around the maturity date. `*_mandatory` is true for mandatory/automatic
  conversion, false for voluntary/at-lender's-option.
- `valuation_cap` / `valuation_floor`: the CHF (or loan-currency) company
  valuation amounts, not per-share prices.
- `discount_pct`: the discount as a percentage (e.g. 20 for "80% of the
  subscription price"). If the discount changes over time, put the currently
  earliest applicable rate here and describe the full schedule verbatim-ish in
  `discount_schedule`; otherwise `discount_schedule` is null.
- `denominator_basis`: whether cap/floor prices divide by fully-diluted
  shares or issued-and-outstanding shares.
- `subordination_scope`: `loan_balance_full` when subordination covers
  principal AND accrued interest (e.g. the SECA "Loan Balance owed now or in
  the future" wording); `principal_only` when only the principal is
  subordinated; `unclear` when subordinated but the covered amount is
  ambiguous; `not_subordinated` when there is no subordination.
- `conversion_capital_source`: how conversion shares are meant to be created:
  shareholder consent declarations (`consents`), conditional capital
  (`conditional_capital`), a capital band (`kapitalband`), or `unstated`.
- `mfn_clause`: a most-favored-nation clause upgrading this lender to better
  terms granted to later lenders.
- `pro_rata_rights`: participation rights of the lender in the future equity
  round beyond the conversion itself.
