Use only the supplied context. Do not invent facts or treat missing retrieved
evidence as proof that something does not exist.

Return strict JSON only, without Markdown fences:

{
  "status": "Not Found | Critical | Borderline | Sufficient | Fine",
  "rationale": "Concise evidence-based explanation.",
  "source_documents": ["Document — page or section"],
  "proposed_next_steps_and_questions": ["Specific action or question"]
}

Use an empty JSON list when there are no source documents or proposed next
steps and questions.
