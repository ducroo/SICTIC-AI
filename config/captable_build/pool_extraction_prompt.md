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

Every extracted row must quote complete source rows with their original column boundaries, including the relevant column header. Headers and rows need not be adjacent: separate them with newlines or `...` between complete lines, never inside a row. For a holding summed across certificates, quote every contributing row exactly once, including repeated equal share amounts; add only the applicable share column, never certificate IDs, dates or other columns. Keep the source holder name intact. A blank holder cell inherits only the preceding named holder within the same table; retain that source context; quote only the contributing numeric rows, not an extra amount merely to repeat the name. Names assembled from scattered tokens or numbers collapsed from multiple columns are ambiguous, not evidence.

Use an explicit dash/none marker as zero only in the relevant numeric column. A blank cell or n/a is unknown: use null where allowed and explain in assumptions. Do not fill an unknown holding with zero. Repair spacing inside a single clearly grouped numeral only; never join digits across cells. If the source cannot establish a holder, field or amount unambiguously, record the limitation rather than inventing evidence. Names and labels retain source wording; roles and kinds are classifications.

Use one exact source label for each pool; do not concatenate category and holder labels with a slash. Category rows may be quoted for a stakeholder’s group, but are not added to that holder’s amounts.
