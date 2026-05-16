import os
from typing import List, Dict
from lib.logger import get_logger
from lib.slugify import slugify
from lib.env import get_env_var

logger = get_logger(__name__)

def generate_output(ranked_results: List[Dict], startup_name: str, safe_llm_name: str) -> str:
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    startup_name_lower = startup_name.lower()
    
    md_lines = ["# Suggested Investors\n", "| Investor Name | Score/Rank | Rationale |", "|---|---|---|"]
    for r in ranked_results:
        md_lines.append(f"| {r['investor_name']} | {r['score']} | {r['rationale']} |")
        
    markdown_output = "\n".join(md_lines)
    
    out_dir = os.path.join(gdrive_mount, "insights", startup_name_lower)
    os.makedirs(out_dir, exist_ok=True)
    raw_filename = f"{startup_name_lower}-potential-investors-{safe_llm_name}"
    out_path = os.path.join(out_dir, f"{slugify(raw_filename)}.md")
    
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(markdown_output)
        
    logger.info(f"Successfully saved ranked investors to {out_path}")
    
    return markdown_output