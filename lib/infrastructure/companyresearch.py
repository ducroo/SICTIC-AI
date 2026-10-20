"""CompanyResearch customer API; no dossier or research lifecycle policy."""

from __future__ import annotations

import asyncio
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

from lib.infrastructure.ai_text_generation.json import validate_json_schema
from lib.infrastructure.configuration import get_env_var, load_repository_config
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind as Kind
from lib.infrastructure.logging import get_logger
from lib.infrastructure.retry import with_rate_limit_retry

logger = get_logger(__name__)


class CompanyResearchError(InfrastructureError):
    """Sanitized provider rejection, including its code for workflow decisions."""

    def __init__(self, *args, status_code, code, **kwargs):
        super().__init__(*args, **kwargs)
        self.status_code = status_code
        self.code = code

    @property
    def concurrency_limited(self):
        return self.status_code == 429 and self.code == "concurrency_limit"


class CompanyResearchAdapter:
    def __init__(self, *, session=None):
        self.settings = load_repository_config("import_companyresearch", "settings")
        self.schemas = load_repository_config("import_companyresearch", "api_schema")
        self.key = (get_env_var("companyresearch_api_key", required=False)
                    or get_env_var("COMPANYRESEARCH_API_KEY"))
        self.session = session or requests.Session()

    async def _request(self, method, path, *, schema, **kwargs):
        retry_at = 0.0
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json",
                   **kwargs.pop("headers", {})}

        async def attempt():
            nonlocal retry_at
            if retry_at > time.time():
                await asyncio.sleep(retry_at - time.time())
            try:
                response = await asyncio.to_thread(
                    self.session.request, method, self.settings["base_url"].rstrip("/") + path,
                    headers=headers,
                    timeout=self.settings["timeout_seconds"], allow_redirects=False, **kwargs,
                )
            except requests.RequestException as error:
                kind = Kind.TIMEOUT if isinstance(error, requests.Timeout) else Kind.SERVICE_UNAVAILABLE
                raise InfrastructureError("Transport failure", kind=kind,
                    provider="companyresearch", operation=path.split("/")[1]) from error
            if response.status_code >= 300:
                try:
                    code = response.json().get("code", "request_rejected")
                except (ValueError, AttributeError):
                    code = "request_rejected"
                # Do not echo provider bodies, request headers or credentials into logs.
                if not isinstance(code, str) or not code.replace("_", "").isalnum():
                    code = "request_rejected"
                if response.status_code in (429, 503):
                    delay = response.headers.get("Retry-After", "0")
                    try:
                        retry_at = time.time() + max(0, float(delay))
                    except ValueError:
                        try:
                            retry_at = parsedate_to_datetime(delay).timestamp()
                        except (ValueError, TypeError, OverflowError):
                            retry_at = 0
                kind = {401: Kind.AUTHENTICATION, 402: Kind.RESOURCE_BUSY,
                        403: Kind.PERMISSION_DENIED, 429: Kind.RATE_LIMIT,
                        503: Kind.SERVICE_UNAVAILABLE}.get(response.status_code, Kind.INVALID_RESPONSE)
                if response.status_code == 429 and code == "concurrency_limit":
                    kind = Kind.RESOURCE_BUSY
                raise CompanyResearchError(f"HTTP {response.status_code}: {code}", kind=kind,
                    provider="companyresearch", operation=path.split("/")[1],
                    status_code=response.status_code, code=code,
                    recoverable=response.status_code in (429, 503))
            try:
                data = response.json()
                validate_json_schema(data, {"$defs": self.schemas["$defs"], **schema},
                                     label="CompanyResearch response")
            except (ValueError, TypeError) as error:
                raise InfrastructureError("Invalid API response", kind=Kind.INVALID_RESPONSE,
                    provider="companyresearch", operation=path.split("/")[1]) from error
            return data

        return await with_rate_limit_retry(attempt,
            is_rate_limit=lambda e: isinstance(e, CompanyResearchError)
                and e.status_code in (429, 503) and not e.concurrency_limited,
            logger=logger, label="CompanyResearch")

    async def suggestions(self, query):
        data = await self._request("GET", "/company-suggestions", params={"q": query},
            schema={"type": "object", "required": ["items"], "properties": {
                "items": {"type": "array", "maxItems": 10,
                          "items": {"$ref": "#/$defs/CompanySuggestion"}}}})
        return data["items"]

    def close(self):
        self.session.close()

    async def submit(self, uid, key):
        return await self._request("POST", "/research-requests",
            headers={"Idempotency-Key": key}, json={"uid": uid, "refresh": False},
            schema={"$ref": "#/$defs/ResearchReceipt"})

    async def receipt(self, request_id):
        return await self._request("GET", "/research-requests/" + quote(request_id, safe=""),
                                  schema={"$ref": "#/$defs/ResearchReceipt"})

    async def report(self, uid, run_id):
        # Construct the endpoint ourselves; never send credentials to a returned URL.
        return await self._request("GET", f"/companies/{quote(uid, safe='')}/reports/{quote(run_id, safe='')}",
                                  schema={"$ref": "#/$defs/CompanyReport"})
