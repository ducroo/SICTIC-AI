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
