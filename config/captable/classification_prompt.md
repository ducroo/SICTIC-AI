You are classifying the documents of a startup's due-diligence data room for
cap-table and convertible-loan analysis. You are given every document in the
dataset: its filename and the beginning of its parsed text content.

Classify EVERY document into exactly one class:

- `current_cap_table`: a capitalization table describing the ACTUAL, current
  ownership of the company (shareholders, share counts, share classes).
- `forecast_scenario_model`: a cap-table or financial model describing
  HYPOTHETICAL or future states (round scenarios, dilution calculators,
  forecast plans). A file that mixes an actual table with scenario tabs is
  still `forecast_scenario_model` only if no current state can be read from it;
  otherwise prefer `current_cap_table` and mention the scenario tabs in the
  rationale.
- `share_register`: the formal register of shareholders (Aktienbuch /
  registre des actions), typically listing registered holders and share
  numbers with legal formalities.
- `cla_executed`: a convertible loan agreement that appears SIGNED/executed
  (signature pages completed, "signed" in filename, or executed wording).
- `cla_term_sheet`: a convertible-loan term sheet, draft, or an unsigned
  agreement.
- `cla_side_doc`: a document about a convertible loan that is not the
  agreement itself (board resolution approving it, shareholder consent
  declaration, conversion notice).
- `articles_of_association`: Statuten / articles, incorporation deed, public
  deeds changing capital (capital increases, conditional capital, Kapitalband).
- `commercial_register_extract`: Handelsregisterauszug / commercial register
  extract.
- `sha_or_priced_term_sheet`: a shareholders' agreement or a term sheet for a
  PRICED equity round.
- `syndicate_agreement`: pooling / syndicate / nominee agreement among
  co-investors.
- `warrant_agreement`: standalone warrant or option agreement outside an
  employee plan.
- `esop_psop_plan`: employee participation plan documents or pool overviews
  (ESOP/PSOP regulations, allocation agreements, pool spreadsheets).
- `tax_ruling`: a cantonal tax ruling (Steuerruling) or correspondence with a
  tax administration about equity/participation valuation.
- `employment_or_advisor_agreement`: employment, advisor, or founder service
  agreements.
- `other`: none of the above (pitch decks, technical decks, KYC forms,
  beneficial-owner declarations, generic correspondence).

For every document also report:
- `as_of_date`: the date the document's CONTENT speaks as of (statement date,
  execution date, register date), format YYYY-MM-DD; use YYYY-MM or YYYY if
  only partially known; null if no date can be read. Dates in filenames count
  as evidence.
- `language`: main language of the document text (e.g. "en", "de", "fr",
  "en+de" for bilingual).
- `confidence`: 0-100 for the class assignment.
- `rationale`: one or two sentences citing the concrete evidence (filename
  hints AND content evidence).

Rules:
- Classify every listed document; do not skip, merge, or invent filenames.
- Judge from the text excerpt first; filenames are supporting evidence only.
- A scanned/garbled excerpt is not a reason to guess: lower the confidence
  and say what is unreadable in the rationale.
