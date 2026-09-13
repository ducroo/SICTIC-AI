# Synthetic captable fixture dataset

A tiny, fully synthetic startup data room ("Fixture Robotics AG") with a
known answer key (`ground_truth.json`). It is the regression dataset for
the captable pipeline: every quirk the real data rooms taught us is planted
here with a known correct reading, so one cheap build covers all of them.

## Install and run

Markdown sources sync in seconds (no OCR). Copy every data-room file, but
never the answer key or this README:

```bash
DATA="$LOCAL_STORAGE_PATH/storage/startups/synthcap/datasets"
mkdir -p "$DATA"
find tests/fixtures/captable -type f ! -name README.md ! -name ground_truth.json \
     -exec cp {} "$DATA/" \;
conda run -n sictic-env python -m skills.dataset_chat sync synthcap --force
conda run -n sictic-env python -m skills.captable_build build --startup synthcap --fresh
```

The build runs on the configured `LLM_MODEL`; `--model` overrides it (the
key must fit that provider). A correct run ends with seven validation
checks, all passing, and the extraction matching `ground_truth.json`.
Correction rounds in the log show which planted case the model got wrong
first. The build compares no cap-table versions with each other, so the
planted Bruno anomaly never shows up in a build; the model-free suite
exercises it through the cross-version primitive.

The model-free half of the regression is
`tests/skills/test_captable_fixture_regressions.py`: for every planted row
it asserts that the evidence reviewer accepts the faithful extraction and
rejects the classic mistake, and that the validators reach the expected end
state over those extractions. Run it with the rest of the suite.

## Documents

| File | Class | What it plants |
|---|---|---|
| `synthetic_captable.md` | current_cap_table, 2026-03-31 | Bridge anchor, unchanged: group rows, an option-only holder, treasury (issued but not diluting), a grantable pool listed as group + identical single member (extract once, merge in `assumptions`). Share classes are named only by column headers (a header-only class quote is allowed and evidences no number). |
| `synthetic_captable_v2.md` | current_cap_table, 2026-06-30 | Supersedes v1. Helvetia Growth joins with 100,000 preferred A, Bruno drops 300,000 → 250,000 with Emil Weg appearing (no transfer document: the cross-version primitive must warn `shrinking_holder`), 15,000 options granted to Diego (pool 25,000 → 10,000). A share-class table with nominal value and votes per share gives `share_classes` real source rows. |
| `synthetic_register.md` | share_register, 2026-03-31 | German OCR-style Aktienbuch over three pages. Page 2 opens with a running page header and a nameless continuation row that the converter declares as a header; the page-3 marker sits directly between two rows. Anna's holding is the sum of her named certificate row on page 1 and that continuation row (250'000 + `150 ' 000`); Bruno's cell stacks his history (`200'000 300'000`, last figure current) and his remark carries an `&#124;`; Alpina's common cell says `n/a` (null, never 0) next to `500 ' 000`; the treasury row reads `100 000` and a lone `#`. Dashes evidence 0, blanks evidence nothing. Names carry middle names and domiciles (`Anna Barbara Beispiel, Zürich`, `Fixture Robotics AG, Zürich (eigene Aktien / treasury)`) and must still reconcile. |
| `synthetic_pool_overview.md` | esop_psop_plan, 2026-03-31 | Sheet export: an all-empty first row declared as the header, the pool named on a section row, key-value rows, a `#` cell, a label carrying a number that is not the figure (`% of shares issued (1,300,000)`), granted stated as a literal 0, unallocated derived. |
| `synthetic_esop_plan.md` | esop_psop_plan, 2026-02-15 | Prose plan summary: the pool is named by the title heading, `Date:` is split from its value by a blank line, the key terms are a wrapped bullet list. Same 25,000 pool, so three sources must agree. |
| `synthetic_cla.md` | cla_executed, 2026-01-15 | Two lenders with per-lender amounts (Petra 200,000 + Bruno 50,000 = 250,000). Bruno is a founder shareholder: `cla_lender_is_shareholder` must report pass/info for him only. The three-party block tempts a model to list the borrower as a third lender; the CLA reviewer rejects that. `valuation_floor` and `pro_rata_rights` are deliberately absent and must be reported in `missing_terms`. |
| `fixture_logo.ai` | (never classified) | Design-asset decoy: ingestion must skip it. |

Registers and pool documents are dated at or before March and must be
reconciled against the MARCH cap table (nearest-dated), where everything
matches; comparing them against the June version was the date-skew bug
this fixture first caught. Cumulative invested capital (CHF 1,450,000) is
deliberately not equal to the issued share count (1,400,000), so the
stamp-duty figure can never be mistaken for a share count.

## Expected end state

All validation checks pass (`issued_total_*`, `diluted_equation`,
`diluted_rowsum`, `register_reconciliation` with no `register_only_holder`,
`pool_consistency` over three sources, `cla_lender_is_shareholder` as
pass/info), and `nominal_floor` and `cla_possibly_converted` do not fire.
Over the two versions, the cross-version primitive reports exactly one
finding, the `shrinking_holder` warning for Bruno (model-free suite only).
`ground_truth.json` lists the per-row values, including which register
cells are 0 and which are null, and maps every learning to the document
that exercises it (`coverage`).

## Not exercised

Listed in `ground_truth.json` under `not_exercised`, each with the unit test
that covers it instead: projected year columns and subsidiary registers
(open gaps), a new table declaring its own header right after a page break,
phantom pools, a numeral split at its apostrophe into the next cell,
and the retry-only-failed-documents behaviour (the fixture cannot make a
document fail deterministically).

All names and numbers are invented; any resemblance to real companies is
coincidental. Keep it that way: synthetic fixtures exist so development
sessions never need real data-room content.
