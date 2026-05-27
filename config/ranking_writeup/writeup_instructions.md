-------------------- PROFILES WITH HIGHEST RANK -------------------------------------
{{profiles_text}}

-------------------- INSTRUCTIONS -----------------------------

{{objective}}

**Execution**
Above is the final ranking of the profiles. Your explicit task is to evaluate each profile against the Objective and provide a balanced rationale covering both their strengths and weaknesses.

Instructions:
1. Derive a human-readable profile_name from the Profile ID.
2. Write a balanced_rationale_for_ranking (a concise 2-3 sentence explanation to what extent they match the Objective).
3. Return ONLY valid JSON matching this exact structure:
{
  "results": [
    {
      "profile_id": "id_from_above",
      "profile_name": "Extracted Name",
      "balanced_rationale_for_ranking": "Rationale text..."
    }
  ]
}
Do not provide any explanations or text outside of the JSON block.
