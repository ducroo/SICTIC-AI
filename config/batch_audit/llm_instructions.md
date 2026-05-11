Output Format: Strict JSON only. Do not wrap in markdown fences.
Fields:
* "status": Exactly one of: "Not Found", "Critical", "Borderline", "Sufficient", "Fine". 
* "summary": Concise findings. If context is missing/irrelevant, state "Not Found". Cite sources as (Document, Page) if present in the context. 
* "concerns": Red flags phrased as questions. If none, state "None". 

If no chunks are relevant, return the JSON with 'Not Found' values.