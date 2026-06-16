---
name: dd_checks
description: Performs a comprehensive M&A-style due diligence review of a startup's data room using predefined, industry-aware checklists. It automatically identifies the startup's industry, selects the appropriate checklists, searches the data room, and generates a single, complete Markdown report file in the background.
---

# M&A Due Diligence Checklist

This skill automates a thorough, background due diligence review of a specified startup's data room and outputs the findings to a single Markdown file. It dynamically evaluates chapters (such as elevator, corporation, team, financials, commercial, risks, and product) based on the startup's industry type.

## Trigger

Use this skill when asked to perform due diligence, run a DD checklist, or review a data room for a startup. Example: "Run the dd_checks for Avientus".

## Workflow

The skill executes a python script in the background that manages the process:

1. **Profiling (First Step):** Uses `dataset_chat` to identify the startup's industry type. It dynamically extracts the allowed industry types from the checklist keys and uses the prompts located at `config['dd_checks']['industry_type_query']` and `config['dd_checks']['industry_type_llm_instructions']`.
2. **Checklist Selection & Extraction:** 
   1. The script reads the available checklist keys from `config['dd_checks']['checklists']`. These keys are formatted as `<chapter>_<industry_type>` (e.g., `1_elevator_general`).
   2. It distills the unique chapters from these keys.
   3. For each chapter, it selects the key that matches the identified `<industry_type>`. If an industry-specific version doesn't exist for that chapter, it falls back to the `general` version.
3. **Comprehensive Review:** For each selected checklist, it uses `batch_audit` to process all items against the data room.
4. **Resiliency:** If a chapter fails (e.g., LLM timeout, context window limit), the script logs the error inside the Markdown output file for that specific chapter, safely catches the exception, and continues processing the remaining chapters.
5. **Output:** All chapter results are collated into one Markdown report, saved with `lib.insights.InsightFile(dataset=startup_slug, skill="dd_checks", model=llm_model(), prompt_key=<industry_and_checklist_config>)`, and returned as `insight.path`. Do not hardcode `<REPO_PATH>/insights/...` paths.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /dd_checks "<STARTUP_NAME>"
```
