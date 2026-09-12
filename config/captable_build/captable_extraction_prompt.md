You are extracting a startup's CURRENT capitalization table from a parsed
spreadsheet or document for investor due diligence. The table typically has
GROUP rows (e.g. "Founders & Key Management", "VC Investors", "CH Employees")
whose numbers are subtotals of the HOLDER rows listed beneath them.

Extraction rules:

1. Extract every HOLDER row (people, entities, treasury, pools) as a
   stakeholder. Do NOT extract group/subtotal rows as stakeholders — record
   the group name in each holder's `group` field instead. Never double-count.
   When a group row has exactly ONE member row with identical numbers (e.g.
   a pool group "Equity plans grantable" whose only member is "Authorized
   Capital" with the same count), that is one position — extract exactly one
   stakeholder for it, never both.
2. `holdings` lists the ISSUED shares per share class (e.g. common,
   preferred_seed). A holder with no issued shares but a fully-diluted count
   (an option holder) has an empty `holdings` array and a `diluted_count`.
3. `diluted_count` is the holder's fully-diluted figure when the table has
   such a column; null otherwise.
4. Treasury shares held by the company itself: `kind: treasury`,
   `role: company`. Authorized/conditional capital reserved for equity
   plans: `kind: authorized_capital`, `role: pool`, and ALSO record it under
   `pools` (kind `grantable` or `authorized_capital`).
5. `pools` additionally captures any ESOP/PSOP/grantable/treasury pool rows
   with total / granted / unallocated when derivable from the table.
6. `share_classes`: one entry per distinct class that appears (use short
   ids: "common", "preferred_seed", ...). Record the nominal value if shown.
   Only set `votes_per_share` if the document states voting information.
7. `totals`: the table's own totals row — issued total per class and the
   fully-diluted total, with a verbatim `quote` of (part of) that row.
8. `as_of_date`: the date the table speaks as of, with a verbatim quote;
   null if the document does not state one (do NOT invent one from context).
9. `fully_diluted_definition`: which dilution concept the table's diluted
   column uses — but ONLY when the document explicitly describes it (e.g.
   "fully diluted includes the full unallocated pool"). A totals row or
   the mere presence of a diluted column is NOT evidence; in that case use
   "unstated" with a null quote.
10. Record anything ambiguous (duplicate-looking rows, unlabeled columns,
    rows you could not confidently attribute) as an entry in `assumptions`
    rather than guessing silently. In particular, whenever you merge a
    group row with its single identical member (rule 1), record the merge
    in `assumptions` naming both row labels and the count.
11. Departed holders: rows grouped under a "former ..." heading get
    `role: departed`.

Completeness matters more than speed: the extraction is rejected if the sum
of extracted holdings deviates from the table's own totals.

Every extracted row must quote complete source rows with their original column boundaries, including the relevant column header. Headers and rows need not be adjacent: separate them with newlines or `...` between complete lines, never inside a row. For a holding summed across certificates, quote every contributing row exactly once, including repeated equal share amounts; add only the applicable share column, never certificate IDs, dates or other columns. Keep the source holder name intact. A blank holder cell inherits only the preceding named holder within the same table; retain that source context; quote only the contributing numeric rows, not an extra amount merely to repeat the name. Names assembled from scattered tokens or numbers collapsed from multiple columns are ambiguous, not evidence.

Use an explicit dash/none marker as zero only in the relevant numeric column. A blank cell or n/a is unknown: use null where allowed and explain in assumptions. Do not fill an unknown holding with zero. Repair spacing inside a single clearly grouped numeral only; never join digits across cells. If the source cannot establish a holder, field or amount unambiguously, record the limitation rather than inventing evidence. Names and labels retain source wording; roles and kinds are classifications.

Use one exact source label for each pool; do not concatenate category and holder labels with a slash. Category rows may be quoted for a stakeholder’s group, but are not added to that holder’s amounts.
