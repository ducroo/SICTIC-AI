---
name: jury_priorities
description: Format and synthesize an existing saved rating report into four non-ratable jury briefing sections without running checks or ingesting source data.
---

# Jury priorities

Turn an existing saved rating report into a concise jury-facing briefing. This
public skill is a non-ratable formatter/synthesis contract: it does not
implement the report-producing workflow or independently assess a startup.

## Inputs and outputs

The async `jury_priorities(startup)` returns one `InsightFile` in a flat list,
named `jury-priorities-<startup>-<model>.md`. It reads the preferred saved
`jury_rating` insight as an opaque report; the report-producing workflow is not
part of this contribution.

The briefing contains exactly four sections: Team, Business opportunity,
Product, and Documentation. It contains no generated score or decision label.
Each section has a report-backed evidence excerpt; questions may be absent.

## Workflow and limitations

1. Resolve the canonical startup slug and read an existing saved rating report.
2. Stop with a clear instruction to create the saved report when none exists or
   when it is empty.
3. Send only that report and the public synthesis instructions to one
   schema-constrained generation call.
4. Require exactly the four section names, at least one exact evidence excerpt
   per section, and render sections in the documented order. Evidence excerpts
   are checked for verbatim presence in the selected report; summaries and
   questions are not semantic-proof guarantees.
5. Save the briefing as a separate `jury_priorities` insight.

No source discovery, checklist execution, semantic search, document ingestion,
auxiliary-source access, scoring, real-startup assessment, or production-
readiness determination is performed here.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/jury_priorities "<STARTUP>"'
```

The direct CLI uses `--startup` (and `-s`).

## References

- [Implementation](jury_priorities.py)
- [Synthesis instructions](../../config/jury_priorities/llm_instructions.md)
- [Response schema](../../config/jury_priorities/response_schema.json)
