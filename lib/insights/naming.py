from pathlib import PurePosixPath

from lib.env import get_env_var
from lib.slugify import slugify


def insight_base_name(filename: str) -> str:
    """Return the identifier portion of a canonical insight filename."""
    stem = PurePosixPath(filename).stem
    ranked_models = [
        slugify(model.split("/")[-1])
        for model in get_env_var("RANKED_LLMS").split(",")
        if model.strip()
    ]
    for model in sorted(ranked_models, key=len, reverse=True):
        suffix = f"-{model}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)]

    # Legacy and unranked files still need to be readable during migration.
    import re

    return re.sub(
        r"-(gpt|claude|gemini|gemma|qwen|deepseek|llama|mixtral|phi|mistral)"
        r"[\w.-]*$",
        "",
        stem,
        flags=re.IGNORECASE,
    )


def insight_model_slug(filename: str) -> str | None:
    stem = PurePosixPath(filename).stem
    if stem.endswith("-manual"):
        return "manual"
    ranked_models = [
        slugify(model.split("/")[-1])
        for model in get_env_var("RANKED_LLMS").split(",")
        if model.strip()
    ]
    for model in sorted(ranked_models, key=len, reverse=True):
        if stem.endswith(f"-{model}"):
            return model

    import re

    match = re.search(
        r"-((?:gpt|claude|gemini|gemma|qwen|deepseek|llama|mixtral|phi|mistral)"
        r"[\w.-]*)$",
        stem,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None
