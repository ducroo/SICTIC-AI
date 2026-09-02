"""Generic access to Apify actors and runs."""

from datetime import timedelta

from apify_client import ApifyClient

from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ApifyAdapter:
    def __init__(self):
        self.token = get_env_var("APIFY_KEY")
        self.client = ApifyClient(self.token)

    def run_actor(self, actor_id: str, run_input: dict) -> list:
        try:
            logger.info("Starting Apify Actor %s", actor_id)
            run = self.client.actor(actor_id).call(run_input=run_input)
            dataset_id = _run_value(run, "defaultDatasetId", "default_dataset_id")
            if not dataset_id:
                raise RuntimeError("Apify actor finished without a default dataset ID")
            results = list(self.client.dataset(dataset_id).iterate_items())
            logger.info(
                "Successfully ran Apify Actor %s; retrieved %d items",
                actor_id,
                len(results),
            )
            return results
        except Exception as error:
            logger.error("Apify Actor %s failed: %s", actor_id, error)
            raise RuntimeError(f"Apify API error: {error}") from error

    def start_actor(self, actor_id: str, run_input: dict) -> str:
        try:
            run = self.client.actor(actor_id).start(run_input=run_input)
            run_id = _run_value(run, "id")
            if not run_id:
                raise RuntimeError("Apify actor started without a run ID")
            return str(run_id)
        except Exception as error:
            logger.error("Failed to start Apify Actor %s: %s", actor_id, error)
            raise RuntimeError(f"Apify API error: {error}") from error

    def wait_for_run(self, run_id: str, wait_seconds: int) -> dict:
        try:
            run = self.client.run(run_id).wait_for_finish(
                wait_duration=timedelta(seconds=wait_seconds),
            )
            return _run_dict(run)
        except Exception as error:
            raise RuntimeError(f"Apify API error: {error}") from error

    def get_run(self, run_id: str) -> dict:
        try:
            return _run_dict(self.client.run(run_id).get())
        except Exception as error:
            raise RuntimeError(f"Apify API error: {error}") from error

    def run_items(self, run: dict) -> list[dict]:
        dataset_id = _run_value(run, "defaultDatasetId", "default_dataset_id")
        if not dataset_id:
            raise RuntimeError("Apify run has no default dataset ID")
        try:
            return list(self.client.dataset(dataset_id).iterate_items())
        except Exception as error:
            raise RuntimeError(f"Apify API error: {error}") from error

    def delete_run(self, run_id: str) -> None:
        try:
            self.client.run(run_id).delete()
        except Exception as error:
            logger.warning("Failed to delete assessed Apify run %s: %s", run_id, error)


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


def _run_dict(run) -> dict:
    if run is None:
        raise RuntimeError("Apify run does not exist")
    if isinstance(run, dict):
        return run
    if hasattr(run, "model_dump"):
        return run.model_dump(by_alias=True)
    raise RuntimeError(f"Unsupported Apify run object: {type(run).__name__}")
