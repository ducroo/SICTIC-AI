import os
import sys
from datetime import datetime
from typing import List, Dict, Any
from lib.api_client import BaseAPIClient


from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)


class RcloneAdapter:
    def __init__(self):
        self.rclone_url = get_env_var("RCLONE_HOST").rstrip("/")
        self.gdrive_mount = get_env_var("GDRIVE_MOUNT")

    def refresh_vfs(self, path: str):
        try:
            BaseAPIClient.post(f"{self.rclone_url}/vfs/refresh", json_data={"dir": path}, retries=1)
        except Exception as e:
            logger.warning(f"Failed to refresh rclone VFS: {e}")

    def list_files(self, path: str) -> List[Dict[str, Any]]:
        local_path = f"{self.gdrive_mount}/{path}"
        files = []
        if os.path.exists(local_path):
            for root, dirs, filenames in os.walk(local_path):
                for f in filenames:
                    f_path = os.path.join(root, f)
                    if os.path.isfile(f_path):
                        mod_time = os.path.getmtime(f_path)
                        rel_path = os.path.relpath(f_path, local_path)
                        files.append({
                            "Name": rel_path,
                            "ModTime": datetime.fromtimestamp(mod_time).isoformat() + "Z"
                        })
        return files
