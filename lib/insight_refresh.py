import re
from pathlib import PurePosixPath
from typing import List, Optional, Tuple, Iterator

from lib.env import get_env_var
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage
from lib.storage_domains import dataset_raw_path

logger = get_logger(__name__)

KNOWN_MODELS_REGEX = re.compile(
    r'-(gpt|claude|gemini|gemma|qwen|deepseek|llama|mixtral|phi|mistral)[\w.-]*$', 
    re.IGNORECASE
)

def get_base_name(filename: str) -> str:
    """Strips the model suffix and .md extension to return pure entity name."""
    stem = PurePosixPath(filename).stem
    try:
        for model in sorted(_ranked_model_slugs(), key=len, reverse=True):
            suffix = f"-{model}"
            if stem.endswith(suffix):
                return stem[: -len(suffix)]
    except Exception:
        pass
    return KNOWN_MODELS_REGEX.sub('', stem)

def _ranked_model_slugs() -> List[str]:
    ranked_llms = get_env_var("RANKED_LLMS")
    return [slugify(m.split("/")[-1]) for m in ranked_llms.split(",") if m.strip()]


def ranked_alternatives(filename: str, directory_files: List[str]) -> Iterator[str]:
    """
    Yields filenames from directory_files that match the base_name of the provided filename,
    strictly ordered by RANKED_LLMS priority.
    """
    base_name = get_base_name(filename)
    available_files = set(directory_files)
    for model in _ranked_model_slugs():
        expected_name = f"{base_name}-{model}.md"
        if expected_name in available_files:
            yield expected_name


def best_alternative(filename: str, directory_files: List[str]) -> Iterator[str]:
    """
    Yields ranked alternatives first, then remaining files that share the base name.
    """
    ranked = list(ranked_alternatives(filename, directory_files))
    yield from ranked

    base_name = get_base_name(filename)
    available_files = set(directory_files) - set(ranked)
    remaining_matches = []
    for f in list(available_files):
        if get_base_name(f) == base_name:
            suffix = PurePosixPath(f).stem[len(base_name):]
            numbers = [int(n) for n in re.findall(r'\d+', suffix)]
            max_num = max(numbers) if numbers else 0
            remaining_matches.append((max_num, f))
            
    # Sort descending by max_num, yield the files
    remaining_matches.sort(key=lambda x: x[0], reverse=True)
    for _, f in remaining_matches:
        yield f


def check_insight_refresh(
    datasets: List[str], file_path: str
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Returns (needs_refresh, content, matched_file_path).
    Checks if there is an up-to-date insight file using best_alternative generator.
    """
    storage = get_storage()

    # Pre-compute the max source mtime across all datasets once
    max_source_mtime = 0.0
    for name in datasets:
        dataset_slug = slugify(name)
        dataset_rel = dataset_raw_path(dataset_slug)
        for _, mtime in storage.list_with_mtime(dataset_rel, recursive=True):
            if mtime > max_source_mtime:
                max_source_mtime = mtime

    # Find the directory and target filename
    parts = file_path.split("/")
    dir_path = "/".join(parts[:-1]) if len(parts) > 1 else ""
    target_filename = parts[-1]
    
    # Get all files in that directory
    available_files = [PurePosixPath(f).name for f, _ in storage.list_with_mtime(dir_path)] if storage.exists(dir_path) else []

    # Cache refresh is strict: only ranked LLM outputs are acceptable.
    for candidate_name in ranked_alternatives(target_filename, available_files):
        candidate_rel = f"{dir_path}/{candidate_name}" if dir_path else candidate_name
        
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
