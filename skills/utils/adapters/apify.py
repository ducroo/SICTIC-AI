import json
from apify_client import ApifyClient
from skills.utils.env import get_env_var
from skills.utils.logger import get_logger

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
            
            # Fetch and return Actor results from the run's dataset
            results = []
            for item in self.client.dataset(run["defaultDatasetId"]).iterate_items():
                results.append(item)
                
            logger.info(f"Successfully ran Apify Actor {actor_id}. Retrieved {len(results)} items.")
            return results
        except Exception as e:
            logger.error(f"Apify Actor {actor_id} failed: {e}")
            raise RuntimeError(f"Apify API error: {e}")