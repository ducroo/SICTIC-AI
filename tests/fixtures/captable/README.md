# Synthetic captable fixture dataset

A tiny, fully synthetic startup data room ("Fixture Robotics AG") with a
known answer key (`ground_truth.json`). Two purposes:

1. **Cheap smoke runs** of the whole captable_build pipeline (a few thousand
   tokens instead of multi-megabyte scanned data rooms). Combine with the
   cheap-model override:

   ```bash
   # install as a dataset (markdown sources sync in seconds, no OCR):
   mkdir -p "$LOCAL_STORAGE_PATH/storage/startups/synthcap/datasets"
   cp tests/fixtures/captable/synthetic_*.md \
      "$LOCAL_STORAGE_PATH/storage/startups/synthcap/datasets/"
   python -m lib.cli  # or any dataset sync entry point, then:
   python -m skills.captable_build build --dataset synthcap \
       --model gemini/gemini-3.5-flash-lite --fresh
   ```

2. **Extraction accuracy evals**: every CLA term has a known value, and
   `valuation_floor` / `pro_rata_rights` are deliberately absent — a correct
   extraction reports them in `missing_terms` (the anti-laziness recall
   check). The cap table exercises group rows, an option-only holder,
   treasury (issued but not diluting), a grantable pool listed as group +
   single member (must be extracted once), and the register contains a
   middle-name variant ("Anna Barbara Beispiel" vs "Anna Beispiel") for the
   name-matching reconciliation.

All names and numbers are invented; any resemblance to real companies is
coincidental.
