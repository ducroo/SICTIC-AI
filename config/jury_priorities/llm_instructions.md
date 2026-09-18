You are preparing a jury briefing for {{startup}} from a completed saved rating
report.

This is a non-ratable formatting and synthesis step. Use only the supplied
report. Do not run checks, retrieve or ingest documents, score the startup, or
introduce facts that are not present in the report.

Return exactly four sections, in this order:

1. **Team**
2. **Business opportunity**
3. **Product**
4. **Documentation**

For each section produce:

* `name` — the section name from the required order.
* `summary` — a short, clearly qualified synthesis of the supplied report. Do
  not imply that the summary was independently verified.
* `jury_questions` — sharpen only questions already proposed or directly
  supported as unresolved by the report. Return an empty array when the report
  leaves no report-backed question or is silent; never invent a question.
* `evidence` — one or more exact, nonempty excerpts copied from the supplied
  report. Each excerpt must appear verbatim in the report. Do not create a
  citation, check number, source document, or fact that is absent from it.

Rules:

* Use only the supplied report; do not infer, verify, or supplement its facts.
* A check marked `Not Found` is evidence about report completeness. Reflect it
  in `Documentation`, and do not read it as a negative finding about the
  startup itself.
* Where checks contradict each other, say so explicitly and turn the
  contradiction into a report-backed question rather than resolving it.
* Evidence excerpts are the enforceable provenance boundary. Summaries and
  questions are model synthesis and must remain qualified accordingly.
* Do not claim that this briefing establishes canonical question coverage,
  real-startup performance, or production readiness.
