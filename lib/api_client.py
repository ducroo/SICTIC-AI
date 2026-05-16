import requests
import time
from lib.logger import get_logger

logger = get_logger(__name__)



class BaseAPIClient:
    @staticmethod
    def post(url: str, json_data: dict = None, data: dict = None, files: dict = None, timeout: int = 300, retries: int = 3):
        for attempt in range(retries):
            try:
                response = requests.post(url, json=json_data, data=data, files=files, timeout=timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                logger.error(f"API POST Error at {url}: {e}")
                if attempt < retries - 1:
                    logger.warning(f"Retrying ({attempt + 1}/{retries})...")
                    time.sleep(2)
                else:
                    raise e

    @staticmethod
    def get(url: str, timeout: int = 30, retries: int = 3):
        for attempt in range(retries):
            try:
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                logger.error(f"API GET Error at {url}: {e}")
                if attempt < retries - 1:
                    logger.warning(f"Retrying ({attempt + 1}/{retries})...")
                    time.sleep(2)
                else:
                    raise e
