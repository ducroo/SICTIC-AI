from typing import List, Dict
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage
from lib.env import get_env_var

logger = get_logger(__name__)

def generate_output(ranked_results: List[Dict], startup_name: str, safe_llm_name: str) -> str:
    startup_name_lower = startup_name.lower()

    md_lines = ["# Suggested Investors\n", "| Investor Name | Score/Rank | Rationale |", "|---|---|---|"]
    for r in ranked_results:
        md_lines.append(f"| {r['investor_name']} | {r['score']} | {r['rationale']} |")

    markdown_output = "\n".join(md_lines)

    raw_filename = f"{startup_name_lower}-potential-investors-{safe_llm_name}"
    out_path = f"insights/{startup_name_lower}/{slugify(raw_filename)}.md"
    get_storage(get_env_var("REPOSITORY_DIR")).write_text(out_path, markdown_output)
    logger.info(f"Successfully saved ranked investors to {out_path}")

    return markdown_output
