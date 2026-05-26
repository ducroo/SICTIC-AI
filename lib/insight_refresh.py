from typing import List, Optional, Tuple

from lib.env import get_env_var
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)

def get_acceptable_models(current_model_suffix: str) -> List[str]:
    raw_acceptable = ""
    try:
        raw_acceptable = get_env_var("RANKED_LLMS")
    except Exception:
        pass

    acceptable_list = [s.strip() for s in raw_acceptable.split(",") if s.strip()]

    slugified_acceptable = [slugify(m) for m in acceptable_list]
    slugified_current = slugify(current_model_suffix)

    models = []
    for m in slugified_acceptable:
        if m not in models:
            models.append(m)

    if slugified_current not in models:
        models.append(slugified_current)

    return models


def check_insight_refresh(
    datasets: List[str], file_path: str, model_name: str
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Returns (needs_refresh, content, matched_file_path).
    Iterates through acceptable LLM outputs by swapping the model_name part of the file_path
    and checks if one is up to date against ALL provided datasets.

    `file_path` is a storage-relative path like "insights/widgetco/foo-qwen3-8b.md".
    """
    storage = get_storage()

    models = get_acceptable_models(model_name)
    current_model_slug = slugify(model_name)

    # Pre-compute the max source mtime across all datasets once
    max_source_mtime = 0.0
    for name in datasets:
        dataset_slug = slugify(name)
        dataset_rel = f"datasets/{dataset_slug}"
        for _, mtime in storage.list_with_mtime(dataset_rel, recursive=True):
            if mtime > max_source_mtime:
                max_source_mtime = mtime

    for m in models:
        candidate_rel = file_path.replace(f"-{current_model_slug}.md", f"-{m}.md")

        if storage.exists(candidate_rel):
            candidate_mtime = storage.mtime(candidate_rel) or 0.0

            if candidate_mtime >= max_source_mtime:
                logger.info(f"Using valid cached insight: {candidate_rel}")
                try:
                    return False, storage.read_text(candidate_rel), candidate_rel
                except Exception as e:
                    logger.warning(f"Failed to read cache {candidate_rel}: {e}")

    logger.info(f"No valid cache found for {file_path}. Refresh needed.")
    return True, None, None
