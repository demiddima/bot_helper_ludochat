# services/db_api/base.py
from __future__ import annotations

import logging
from typing import Optional

import httpx
from config import DB_API_URL, API_KEY_VALUE

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def _log_request(request: httpx.Request):
    """Информируем о исходящем HTTP-запросе (русский текст, без имён функций)."""
    try:
        log.info("HTTP запрос → %s %s", request.method, request.url, extra={"user_id": "system"})
    except Exception:
        pass


async def _log_response(response: httpx.Response):
    """Информируем об ответе; при 4xx/5xx дополнительно логируем сокращённое тело."""
    try:
        req = response.request
        log.info("HTTP ответ ← %s %s → %s", req.method, req.url, response.status_code, extra={"user_id": "system"})
        if response.status_code >= 400:
            text = ""
            try:
                text = response.text[:500]
            except Exception:
                pass
            log.error("HTTP ответ с ошибкой: код=%s, тело(<=500симв)=%s", response.status_code, text, extra={"user_id": "system"})
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
            log.error("HTTP-клиент: ошибка закрытия — ошибка=%s", e, extra={"user_id": "system"})
            raise
