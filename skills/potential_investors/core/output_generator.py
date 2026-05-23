from typing import List, Dict
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)

def generate_output(ranked_results: List[Dict], startup_name: str, safe_llm_name: str) -> str:
    startup_name_lower = startup_name.lower()

    md_lines = ["# Suggested Investors\n", "| Investor Name | Score/Rank | Rationale |", "|---|---|---|"]
    for r in ranked_results:
        md_lines.append(f"| {r['investor_name']} | {r['score']} | {r['rationale']} |")

    markdown_output = "\n".join(md_lines)

    from lib.insight_filepath import get_insight_filepath
    out_path = get_insight_filepath(
        dataset_name=startup_name_lower,
        skill_name="potential_investors",
        model=safe_llm_name,
        subdir=False
    )
    get_storage().write_text(out_path, markdown_output)
    logger.info(f"Successfully saved ranked investors to {out_path}")

    return markdown_output
