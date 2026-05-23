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
    
    # 3. Construct the filename
    if subdir:
        # If placed in a subdirectory named after the skill, omit the skill name from the file
        raw_filename = f"{ident}-{clean_model}.md"
    else:
        # If placed in the root of the dataset, include the skill name in the file
        raw_filename = f"{skill_name}-{ident}-{clean_model}.md"
    
    # 4. Slugify the filename to ensure it is kebab-case and safe
    safe_filename = f"{slugify(raw_filename[:-3])}.md"
    
    # 5. Construct the full path
    safe_dataset = slugify(dataset_name)
    
    if subdir:
        safe_skill = slugify(skill_name)
        return f"insights/{safe_dataset}/{safe_skill}/{safe_filename}"
    else:
        return f"insights/{safe_dataset}/{safe_filename}"
