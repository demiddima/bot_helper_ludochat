# services/db_api/base.py
from __future__ import annotations

import logging
from typing import Optional

import httpx
from config import DB_API_URL, API_KEY_VALUE

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def _log_request(request: httpx.Request):
    try:
        log.info("[api] → %s %s", request.method, request.url)
    except Exception:
        pass


async def _log_response(response: httpx.Response):
    try:
        req = response.request
        log.info("[api] ← %s %s -> %s", req.method, req.url, response.status_code)
        if response.status_code >= 400:
            text = ""
            try:
                text = response.text[:500]
            except Exception:
                pass
            log.error("[api] body: %s", text)
    except Exception:
        pass


class BaseApi:
    def __init__(self, api_url: Optional[str] = None, timeout: float = 10.0) -> None:
        base_url = (api_url or DB_API_URL).rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"X-API-KEY": API_KEY_VALUE},
            event_hooks={"request": [_log_request], "response": [_log_response]},
        )

    async def close(self) -> None:
        try:
            await self.client.aclose()
        except Exception as e:
            log.error("[BaseApi.close] – Ошибка при закрытии клиента: %s", e)
            raise
