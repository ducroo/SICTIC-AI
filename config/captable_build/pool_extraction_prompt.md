You are extracting employee-participation pool figures (ESOP/PSOP/treasury
pools) from a pool overview document, for cross-checking against the cap
table's pool lines.

Rules:

1. One entry per distinct pool the document describes.
2. `total` = the pool's full size; `granted` = options/shares already
   granted/allocated; `unallocated` = remaining. Derive the third when the
   document states two of them; otherwise null.
3. `quote`: a short verbatim snippet evidencing the numbers.
4. `as_of_date`: the document's stated date (filenames don't count), else
   null with an `assumptions` note.
5. Do not guess: ambiguous columns go into `assumptions`.

Every extracted row (holders, share classes, register entries and pools) must include a verbatim `quote` of the source row(s) that state its name/label and its numeric values. Copy each source row exactly as it appears, with its cells in order; when the name sits on a row of its own (a merged cell, a section label) quote that row as well. When a value is the sum of several source rows, quote every row you summed, one source row per line of the quote, and no other row of that holder; use `...` only between lines, never inside a line. The column header may be quoted as an additional line but is never evidence on its own. A number is evidenced only by a source cell that states it: a dash or a 0 in the cell evidences 0, whereas a blank cell, an absent column or "n/a" evidences nothing — report null and note it in `assumptions`, never 0. Do not invent, calculate, round or paraphrase values, and never join digits from different cells. Names and labels must retain the source wording; roles and kinds are classifications.
