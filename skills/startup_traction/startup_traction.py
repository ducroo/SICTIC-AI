from lib.logger import get_logger
from lib.insight_generator import generate_dataset_insight

logger = get_logger(__name__)

async def startup_traction(startup_name: str) -> str:
    """
    Extracts, analyzes, and summarizes all commercial traction and agreements (LoIs, MoUs, Pilot agreements) from a startup's data room into a structured overview table and synthesis.
    """
    return await generate_dataset_insight(
        dataset_name=startup_name,
        skill_name="startup_traction",
        config_key="startup_traction",
        max_chunks=100,
        strict_insufficient_context=False,
    )
