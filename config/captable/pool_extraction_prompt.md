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
