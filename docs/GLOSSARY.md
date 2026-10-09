# Public glossary

<!-- Generated from config/glossary/glossary.json by scripts/build_glossary_doc.py. Do not edit by hand. -->

The public vocabulary and metric-contract matrix for the audit-v2 integration. This file contains public interfaces only; generated documentation is a view, not an input.

## Source contract

- **Visibility:** public
- **Authoritative source:** `config/glossary/glossary.json`
- **Generated view:** `docs/GLOSSARY.md`
- **Source boundary:** only public interfaces are included; derived checklists are not authoritative.

## Dictionary

| identifier | term | definition | public references |
|---|---|---|---|
| `audit-v2` | `audit-v2` | The canonical structured audit envelope produced by the shared checklist engine. | `config/batch_audit/audit_schema.json`, `lib/batch_audit/schema.py::validate_audit_document`, `lib/batch_audit/engine.py::batch_audit` |
| `metric.check-result` | `check-result` | The per-check result value in an audit-v2 document. A successful result is an object; a technical failure is represented by a null result and a non-empty error. | `config/batch_audit/audit_schema.json`, `lib/batch_audit/schema.py::validate_audit_document`, `lib/batch_audit/rendering.py::json_to_markdown_table` |
| `metric.check-error` | `check-error` | The technical error paired with a failed check. It is null for a successful check and non-empty when the result is null. | `config/batch_audit/audit_schema.json`, `lib/batch_audit/engine.py::batch_audit`, `lib/batch_audit/schema.py::validate_audit_document` |

## Metric contract matrix

Each row states what a public producer emits and what public consumers accept.

| identifier | metric | contract | producer | consumers |
|---|---|---|---|---|
| `contract.audit-check-result` | `metric.check-result` | `metric-v1` | `lib/batch_audit/engine.py::batch_audit` (`chapters[].checks[].result`, object, null) | `lib/batch_audit/schema.py::validate_audit_document` (`chapters[].checks[].result`, object, null)<br>`lib/batch_audit/rendering.py::json_to_markdown_table` (`chapters[].checks[].result`, object, null) |
| `contract.audit-check-error` | `metric.check-error` | `metric-v1` | `lib/batch_audit/engine.py::batch_audit` (`chapters[].checks[].error`, string, null) | `lib/batch_audit/schema.py::validate_audit_document` (`chapters[].checks[].error`, string, null)<br>`lib/batch_audit/rendering.py::json_to_markdown_table` (`chapters[].checks[].error`, string, null) |

_This document is generated; edit the JSON source instead._
