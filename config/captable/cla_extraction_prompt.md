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
   `missing_terms`. The same applies to every term marked
   `presence boolean` in the term list below when you report it false —
   "no such clause exists" is an absence claim that a quote cannot
   prove — and to any other boolean reported false or null without a
   supporting quote. Use the exact schema field name as `term` (e.g.
   "valuation_cap", not "cap") and list in `sections_scanned` the concrete
   sections/headings/pages of the document you checked before concluding the
   term is absent. An empty `sections_scanned` is rejected. Being thorough
   here matters more than being fast: absence claims without scan evidence
   are the number-one failure mode of this task.

The terms to extract, with per-term guidance, follow below; the exact
response shape is enforced by the schema.
