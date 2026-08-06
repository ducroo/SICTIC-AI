from lib.insights import InsightFile
from skills.batch_audit.structured import batch_audit_json
from skills.config_load.config_load import config_load


async def batch_audit(
    dataset_name: str,
    checklist_markdown: str,
    *,
    skill_name: str = "batch_audit",
    llm_instructions: str | None = None,
    status_scale: list[str] | None = None,
    missing_evidence_status: str | None = None,
) -> InsightFile:
    """Run a structured checklist and return its canonical JSON Insight."""
    if llm_instructions is None:
        llm_instructions = config_load()["batch_audit"]["llm_instructions"]
    if status_scale is None:
        status_scale = [
            "Not Found",
            "Critical",
            "Borderline",
            "Sufficient",
            "Fine",
        ]
    if missing_evidence_status is None:
        missing_evidence_status = status_scale[0]
    return await batch_audit_json(
        dataset_name=dataset_name,
        skill_name=skill_name,
        checklist_markdown=checklist_markdown,
        llm_instructions=llm_instructions,
        status_scale=status_scale,
        missing_evidence_status=missing_evidence_status,
    )
