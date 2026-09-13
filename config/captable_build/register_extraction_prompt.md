You are extracting the CURRENT holdings from a Swiss share register
(Aktienbuch) for reconciliation against a cap table. Registers are OCR'd
scans: a single table cell often stacks a shareholder's HISTORICAL share
counts (each transfer appended a new figure), and the participation column
stacks the corresponding historical percentages.

Extraction rules:

1. One entry per registered shareholder (people, entities, and the company
   itself for treasury shares).
2. `current_common` / `current_preferred`: the shareholder's CURRENT number
   of shares per class. The current figure is the one consistent with the
   LAST percentage in the participation column and the LAST dated change in
   the transfer column — do NOT simply take the largest or first number.
   When you cannot determine which figure is current, set the count to null
   and explain the ambiguity in `assumptions`.
3. `current_participation_pct`: the last (current) participation percentage
   for the shareholder, as a number (e.g. 26.6 for "26.60%").
4. `first_acquisition_date` / `last_change_date`: from the acquisition and
   transfer/change columns, ISO format where readable.
5. `as_of_date`: the register's own stated date. Registers often leave this
   blank ("as per ______") — then use null and note it in `assumptions`;
   never fill it from a filename.
6. Skip beneficial-owner columns and transfer-history details; this
   extraction exists only to reconcile current holdings.

Every extracted row (holders, share classes, register entries and pools) must include a verbatim `quote` of the source row(s) that state its name/label and its numeric values. Copy each source row exactly as it appears, with its cells in order; when the name sits on a row of its own (a merged cell, a section label) quote that row as well. When a value is the sum of several source rows, quote every row you summed, one source row per line of the quote, and no other row of that holder; use `...` only between lines, never inside a line. The column header may be quoted as an additional line but is never evidence on its own. A number is evidenced only by a source cell that states it: a dash or a 0 in the cell evidences 0, whereas a blank cell, an absent column or "n/a" evidences nothing — report null and note it in `assumptions`, never 0. Do not invent, calculate, round or paraphrase values, and never join digits from different cells. Names and labels must retain the source wording; roles and kinds are classifications.
