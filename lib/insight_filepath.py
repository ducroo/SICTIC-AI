from typing import Optional
from lib.env import get_env_var
from lib.slugify import slugify

def get_insight_filepath(
    dataset_name: str,
    skill_name: str,
    model: str,
    identifier: Optional[str] = None,
    subdir: bool = False
) -> str:
    """
    Constructs a uniform, OS-safe file path for saving skill insight outputs.
    
    Args:
        dataset_name: The domain dataset (e.g., 'daav', 'community').
        skill_name: The name of the skill generating the output (e.g., 'startup_profile').
        model: The raw model string used (e.g., 'ollama/gemma4:31b-nvfp4').
        identifier: The subject of the insight (e.g., 'Urs Gubser'). Defaults to dataset_name.
        subdir: If True, outputs into a folder named after the skill.
    
    Returns:
        A strictly relative path starting with 'insights/...'
    """
    
    # 1. Clean the model string (strip provider)
    clean_model = model.split("/")[-1] if "/" in model else model
    
    # 2. Fallback identifier
    ident = identifier if identifier else dataset_name
    
    # 3. Construct the building blocks for the filename
    safe_dataset = slugify(dataset_name)
    safe_skill = slugify(skill_name)
    safe_core = slugify(f"{ident}-{clean_model}")

    # 4. Construct the final path
    if subdir:
        return f"insights/{safe_dataset}/{safe_skill}/{safe_core}.md"
    else:
        return f"insights/{safe_dataset}/{safe_skill}-{safe_core}.md"
