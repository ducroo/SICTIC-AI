---------------- PIVOT PROFILE ----------------
{{pivot_text}}

---------------- {{n_profiles}} EVALUATION PROFILES ----------------
{{profiles_text}}

---------------- INSTRUCTIONS ----------------

{{objective}}

**Execution**
Your explicit task is to compare the list of {{n_profiles}} profiles with IDs {{IDs_profiles}} against the Pivot profile with ID {{ID_pivot}}, based strictly on the objective provided above.

Instructions:
1. Carefully read the Pivot Profile and understand its value relative to the Objective.
2. For each Profile in the list, compare it to the Pivot Profile.
3. Categorize each Profile into exactly one of the following four buckets:
   - MUCH_BETTER: The Profile is significantly superior to the Pivot.
   - BETTER: The Profile is slightly or moderately superior to the Pivot.
   - WORSE: The Profile is slightly or moderately inferior to the Pivot.
   - MUCH_WORSE: The Profile is significantly inferior to the Pivot.
4. Return ONLY valid JSON matching this exact structure:
{
  "results": [
    {"profile_id": "profile_id_here", "category": "MUCH_BETTER"},
    {"profile_id": "another_profile_id", "category": "WORSE"}
  ]
}
Do not provide any explanations, reasoning, or markdown formatting outside of the JSON block.