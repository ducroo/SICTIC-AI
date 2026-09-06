# Synthetic captable fixture dataset

A tiny, fully synthetic startup data room ("Fixture Robotics AG") with a
known answer key (`ground_truth.json`). Three purposes:

1. **Cheap smoke runs** of the whole captable pipeline (a few thousand
   tokens instead of multi-megabyte scanned data rooms). Combine with the
   cheap-model override:

   ```bash
   # install as a dataset (markdown sources sync in seconds, no OCR):
   mkdir -p "$LOCAL_STORAGE_PATH/storage/startups/synthcap/datasets"
   cp tests/fixtures/captable/synthetic_*.md \
      "$LOCAL_STORAGE_PATH/storage/startups/synthcap/datasets/"
   # after a dataset sync:
   python -m skills.captable_build build --dataset synthcap \
       --model gemini/gemini-3.5-flash-lite --fresh
   ```

2. **Extraction accuracy evals**: every CLA term has a known value, and
   `valuation_floor` / `pro_rata_rights` are deliberately absent — a
   correct extraction reports them in `missing_terms` (the anti-laziness
   recall check). The cap table exercises group rows, an option-only
   holder, treasury (issued but not diluting), a grantable pool listed as
   group + single identical member (must be extracted once, with the merge
   recorded as an assumption), and the register contains a middle-name
   variant ("Anna Barbara Beispiel" vs "Anna Beispiel") for name-matching
   reconciliation.

3. **Versioning and cross-snapshot checks**: two dated cap-table versions
   (2026-03-31 and 2026-06-30). The March→June bridge is fully
   reconcilable — Helvetia Growth joins with 100,000 new preferred A,
   Bruno transfers 50,000 common to Emil Weg (deliberately WITHOUT a
   transfer document: `shrinking_holder` must warn), and 15,000 options
   are granted to Diego from the pool (25,000 → 10,000). Registers and the
   pool overview are dated 2026-03-31 and must be reconciled against the
   MARCH cap table (nearest-dated), where everything matches — comparing
   them against the June version was the date-skew bug this fixture caught.
   Expected end state of a full build: all validation checks pass except a
   single `shrinking_holder` warning.

Note: cumulative invested capital (CHF 1,450,000) is deliberately NOT
equal to the issued share count (1,400,000) so the stamp-duty figure can
never be mistaken for a share count.

Not exercised by this fixture (deliberately plain terms — the fields
come back null, which is correct): the safe-harbor interest cap
(`interest_safe_harbor_rate_pct`; the fixture loan is plain fixed-rate),
a QEFR new-investor minimum (`qefr_min_new_money`; single threshold
only), and a fixed maturity conversion price
(`maturity_conversion_price`; the fixture converts at discount/cap).
Extending the fixture to cover them is a candidate for the eval-suite
follow-up.

All names and numbers are invented; any resemblance to real companies is
coincidental. Keep it that way — synthetic fixtures exist so development
sessions never need real data-room content.
