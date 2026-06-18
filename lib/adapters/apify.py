from apify_client import ApifyClient
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

class ApifyAdapter:
    def __init__(self):
        self.token = get_env_var("APIFY_KEY")
        self.client = ApifyClient(self.token)
        
    def run_actor(self, actor_id: str, run_input: dict) -> list:
        try:
            logger.info(f"Starting Apify Actor {actor_id} with input: {run_input}")
            # Run the Actor and wait for it to finish
            run = self.client.actor(actor_id).call(run_input=run_input)
            dataset_id = _run_value(run, "defaultDatasetId", "default_dataset_id")
            if not dataset_id:
                raise RuntimeError("Apify actor finished without a default dataset ID")
            
            # Fetch and return Actor results from the run's dataset
            results = []
            for item in self.client.dataset(dataset_id).iterate_items():
                results.append(item)
                
            logger.info(f"Successfully ran Apify Actor {actor_id}. Retrieved {len(results)} items.")
            return results
        except Exception as e:
            logger.error(f"Apify Actor {actor_id} failed: {e}")
            raise RuntimeError(f"Apify API error: {e}")


def _run_value(run, *keys: str):
    for key in keys:
        if isinstance(run, dict) and run.get(key):
            return run[key]
        if hasattr(run, "get"):
            try:
                value = run.get(key)
            except Exception:
                value = None
            if value:
                return value
        value = getattr(run, key, None)
        if value:
            return value
    return None
