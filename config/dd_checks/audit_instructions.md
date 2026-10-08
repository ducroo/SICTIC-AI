Use only the supplied context. Do not invent facts or treat missing retrieved
evidence as proof that something does not exist.

Use an empty JSON list when there are no source documents or proposed next
steps and questions.

Select status from the response schema. Use Not Found when supplied evidence
does not address the check; otherwise assess it as Critical, Borderline,
Sufficient or Fine according to the check description.

Give each check an importance from 1 to 10: how much this finding matters for
an angel investor deciding on an early-stage investment (pre-seed to Series A)
in this startup. Use the startup context below to judge what matters most for
its industry.

- 9–10: decisive for the investment decision; a problem here could stop the
  investment.
- 7–8: clearly affects the decision or the terms; a problem here must be
  resolved before closing.
- 4–6: relevant, but a problem here can be handled after the investment.
- 1–3: formal or minor; hardly affects the decision.

Score the finding, not the topic. A routine item that is in order scores low,
even when its topic sounds important. A result that clearly strengthens or
endangers what matters most for this industry scores high. For Not Found,
score how much the missing information matters for the decision at this stage.
Use the whole scale; do not give most checks the same importance.
