import asyncio
import os
import json
import fcntl
import time
from typing import Any, Dict, List
from lib.runtime_noise import configure_runtime_noise

configure_runtime_noise()

import litellm
from enum import Enum
from dotenv import load_dotenv

from lib.logger import get_logger
from lib.env import get_env_var

load_dotenv()

logger = get_logger(__name__)

# CLI commands are short-lived. LiteLLM's aiohttp transport can leave process-global
# sessions open at interpreter shutdown, which prints noisy warnings after successful
# one-shot harness commands. Use httpx transport instead so clients close cleanly.
litellm.disable_aiohttp_transport = True

class Priority(Enum):
    USER = 0      # Live user chats
    STANDARD = 1  # Normal background tasks
    BULK = 2      # Overnight/Bulk jobs

GATEWAY_STATE_FILE = "/tmp/sictic_gateway.json"

class ServicesGateway:
    """
    A serverless IPC gateway using OS-level file locking.
    It manages concurrency across multiple Python scripts by tracking PIDs.
    If a script crashes, its PIDs are automatically garbage-collected by the next script
    that performs an OS health check (os.kill(pid, 0)).
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServicesGateway, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.OLLAMA_NUM_PARALLEL = int(get_env_var("OLLAMA_NUM_PARALLEL"))
        self.DOCLING_NUM_PARALLEL = int(get_env_var("DOCLING_NUM_PARALLEL"))
        
        # Ensure the state file exists with basic structure
        if not os.path.exists(GATEWAY_STATE_FILE):
            try:
                with open(GATEWAY_STATE_FILE, "w") as f:
                    json.dump({"active_docling": [], "active_embeds": [], "active_llms": []}, f)
            except Exception:
                pass
                
        self._initialized = True

    def _clean_pids(self, pids: List[int]) -> List[int]:
        """Returns only the PIDs that are still alive."""
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except OSError:
                pass
        return alive

    def _read_and_clean_state(self, f) -> Dict[str, List[int]]:
        try:
            f.seek(0)
            content = f.read()
            if not content:
                state = {"active_docling": [], "active_embeds": [], "active_llms": []}
            else:
                state = json.loads(content)
                
            # Clean dead processes automatically
            state["active_docling"] = self._clean_pids(state.get("active_docling", []))
            state["active_embeds"] = self._clean_pids(state.get("active_embeds", []))
            state["active_llms"] = self._clean_pids(state.get("active_llms", []))
            return state
        except Exception as e:
            logger.error(f"Error parsing gateway state: {e}")
            return {"active_docling": [], "active_embeds": [], "active_llms": []}

    def _write_state(self, f, state: Dict[str, List[int]]):
        f.seek(0)
        f.truncate()
        json.dump(state, f)
        f.flush()

    async def _acquire_slot(self, resource_type: str, max_concurrent: int, exclusive_against: List[str] = None):
        """
        Polls the OS-locked file until a slot is available.
        Adds the current script's PID to the resource pool.
        """
        pid = os.getpid()
        exclusive_against = exclusive_against or []
        
        while True:
            # We use a blocking open/flock in a thread (or just briefly block the loop since it's local I/O)
            # To be strictly safe in asyncio, we could use run_in_executor, but for a fast local /tmp file, it's fine.
            acquired = False
            with open(GATEWAY_STATE_FILE, "a+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    state = self._read_and_clean_state(f)
                    
                    # Check exclusivity rules
                    can_acquire = True
                    for ex in exclusive_against:
                        if len(state.get(ex, [])) > 0:
                            can_acquire = False
                            break
                            
                    # Check capacity
                    if can_acquire and len(state.get(resource_type, [])) < max_concurrent:
                        state.setdefault(resource_type, []).append(pid)
                        self._write_state(f, state)
                        acquired = True
                    else:
                        # Write the cleaned state anyway, saving future readers time
                        self._write_state(f, state)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

            if acquired:
                return
                
            # Wait and poll again
            await asyncio.sleep(0.5)

    def _release_slot(self, resource_type: str):
        """Removes exactly one instance of the current script's PID from the resource pool."""
        pid = os.getpid()
        with open(GATEWAY_STATE_FILE, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                state = self._read_and_clean_state(f)
                pool = state.get(resource_type, [])
                if pid in pool:
                    pool.remove(pid) # Removes only the first matching occurrence
                    state[resource_type] = pool
                    self._write_state(f, state)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    async def request_embedding(self, kwargs: Dict[str, Any], priority: Priority = Priority.STANDARD) -> Any:
        """Embeddings cannot run concurrently with LLMs or Docling."""
        await self._acquire_slot("active_embeds", self.OLLAMA_NUM_PARALLEL, exclusive_against=["active_llms", "active_docling"])
        try:
            response = await litellm.aembedding(**kwargs)
            return response
        finally:
            self._release_slot("active_embeds")

    async def request_completion(self, kwargs: Dict[str, Any], priority: Priority = Priority.STANDARD) -> Any:
        """LLMs cannot run concurrently with Embeddings or Docling."""
        await self._acquire_slot("active_llms", self.OLLAMA_NUM_PARALLEL, exclusive_against=["active_embeds", "active_docling"])
        try:
            response = await litellm.acompletion(**kwargs)
            return response
        finally:
            self._release_slot("active_llms")

    async def acquire_docling_slot(self, max_concurrent: int):
        """Docling cannot run concurrently with LLMs or Embeddings."""
        await self._acquire_slot("active_docling", max_concurrent, exclusive_against=["active_embeds", "active_llms"])

    def release_docling_slot(self):
        """Releases the global Docling slot."""
        self._release_slot("active_docling")

# Expose a global instance
gateway = ServicesGateway()
