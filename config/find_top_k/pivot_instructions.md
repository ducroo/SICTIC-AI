---------------- PROFILES TO RANK ----------------

{{profiles_text}}

---------------- INSTRUCTIONS ----------------------------

{{objective}}

**Execution**
Your task is to rank the {{n_profiles}} profiles above with IDs: {{IDs_profiles}} from best to worst based STRICTLY on the objective provided above.

Instructions:
1. Carefully analyze each profile against the objective.
2. Determine a strict ranking from the absolute best match to the absolute worst match.
3. Return ONLY valid JSON matching this exact structure:
{
  "ranked_profiles_ids": [
    "best_profile_id",
    "second_best_profile_id",
    "worst_profile_id"
  ]
}
Do not provide any explanations, reasoning, or markdown formatting outside of the JSON block.