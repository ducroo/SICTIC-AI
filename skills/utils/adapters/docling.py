import os
import sys
import json
import time
import asyncio
import aiohttp
from typing import List
from skills.utils.api_client import BaseAPIClient


from skills.utils.env import get_env_var
from skills.utils.logger import get_logger

logger = get_logger(__name__)


class DoclingAdapter:
    def __init__(self, concurrency_limit: int = 10):
        self.docling_url = f'{get_env_var("DOCLING_HOST").rstrip("/")}/v1/convert/file'
        self.docling_async_url = f'{get_env_var("DOCLING_HOST").rstrip("/")}/v1/convert/file/async'
        self.docling_host = get_env_var("DOCLING_HOST").rstrip("/")
        self.vlm_model = get_env_var("DEFAULT_VLM")
        self.ollama_url = get_env_var("OLLAMA_HOST").rstrip("/")
        self.concurrency_limit = concurrency_limit

    async def extract_documents(self, files_to_process: List[dict], oc_base_path: str, docling_base_path: str):
        tasks = []
        for f_data in files_to_process:
            filename = f_data["filename"]
            mod_time = f_data["mod_time"]
            filepath_oc = os.path.join(oc_base_path, filename)
            filepath_docling = os.path.join(docling_base_path, filename)
            
            async def run_task(fname=filename, f_oc=filepath_oc, f_doc=filepath_docling, f_mod=mod_time):
                txt = await self._process_single_file(f_oc, f_doc, fname, f_mod)
                return fname, txt
                
            tasks.append(asyncio.create_task(run_task()))
        
        for coro in asyncio.as_completed(tasks):
            fname, text = await coro
            yield fname, text

    async def _process_single_file(self, filepath_oc: str, filepath_docling: str, filename: str, mod_time: float) -> str:
        from skills.utils.services_gateway import gateway
        await gateway.acquire_docling_slot(self.concurrency_limit)
        try:
            logger.info(f"Sending source file {filepath_oc} to docling-serve for ASYNC processing.")
            
            try:
                if not os.path.isfile(filepath_oc):
                    logger.warning(f"Skipping {filepath_oc}, not a valid local file.")
                    return ""
                    
                if os.path.getsize(filepath_oc) == 0:
                    logger.warning(f"Skipping {filepath_oc}, file is empty (0 bytes).")
                    return ""
                
                if filename.lower().endswith('.json') or filename.lower().endswith('.txt') or filename.lower().endswith('.md'):
                    with open(filepath_oc, 'r', encoding='utf-8', errors='ignore') as f:
                        text = f.read()
                    return text
                    
                vlm_model_name = self.vlm_model
                if vlm_model_name.startswith("ollama/"):
                    vlm_model_name = vlm_model_name[7:]
                    
                api_config = json.dumps({
                    "url": f"{self.ollama_url}/v1/chat/completions",
                    "params": {
                        "model": vlm_model_name,
                        "max_tokens": 200
                    },
                    "prompt": "Describe this image in a few sentences.",
                    "timeout": 600.0
                })
                
                # aiohttp multipart form data
                data = aiohttp.FormData()
                data.add_field("do_ocr", "true")
                data.add_field("image_export_mode", "placeholder")
                data.add_field("image_alt_mode", "description")
                data.add_field("do_picture_description", "true")
                data.add_field("picture_description_api", api_config)
                
                with open(filepath_oc, 'rb') as f:
                    file_data = f.read()
                    
                data.add_field("files", file_data, filename=filename)

                text = ""
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.post(self.docling_async_url, data=data, timeout=30) as response:
                            if response.status >= 400:
                                res_text = await response.text()
                                raise RuntimeError(f"Docling Async POST returned {response.status}: {res_text}")
                            res_json = await response.json()
                            
                        task_id = res_json.get("task_id")
                        if not task_id:
                            raise ValueError(f"No task_id returned. Response: {res_json}")
                            
                        logger.info(f"Async task {task_id} started for {filename}. Polling for completion...")
                        
                        poll_url = f'{self.docling_host}/v1/status/poll/{task_id}'
                        max_wait = 900 
                        start_time = time.time()
                        
                        while True:
                            if time.time() - start_time > max_wait:
                                logger.error(f"Docling async task {task_id} for file {filename} timed out after {max_wait}s. This usually indicates the VLM (Ollama) failed to process an image in time, or Docling hung indefinitely while trying to allocate VRAM/CPU.")
                                raise TimeoutError(f"Docling async task {task_id} timed out after {max_wait}s.")
                                
                            async with session.get(poll_url, timeout=10) as poll_res:
                                poll_json = await poll_res.json()
                                status = poll_json.get("task_status") or poll_json.get("status")
                                
                            if status in ["success", "completed"]:
                                logger.info(f"Task {task_id} completed. Fetching results...")
                                break
                            elif status in ["failed", "aborted", "error"]:
                                raise RuntimeError(f"Task {task_id} failed with status: {status}")
                                
                            await asyncio.sleep(5)
                            
                        result_url = f'{self.docling_host}/v1/result/{task_id}'
                        async with session.get(result_url, timeout=30) as result_res:
                            result_json = await result_res.json()
                            
                        if "document" in result_json and "md_content" in result_json["document"]:
                            text = result_json["document"]["md_content"]
                        else:
                            text = await result_res.text()
                            
                    except Exception as req_err:
                        logger.error(f"Docling request failed for {filename}: {req_err}. Falling back to mock text extraction.")
                        if filename.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx')):
                            logger.error(f"Skipping mock extraction for binary file: {filename}")
                            text = ""
                        else:
                            text = file_data.decode('utf-8', errors='ignore')
                
                if not text:
                    return ""
                
                return text

            except Exception as e:
                logger.error(f"Error processing file {filepath_oc}: {e}")
                return ""
        finally:
            gateway.release_docling_slot()
