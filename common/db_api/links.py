# services/db_api/links.py
from __future__ import annotations
import logging

from .base import BaseApi

log = logging.getLogger(__name__)


class LinksMixin(BaseApi):
    async def track_link_visit(self, link_key: str) -> dict:
        try:
            r = await self.client.post("/links/visit", json={"link_key": link_key})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Ссылки: ошибка учёта перехода — link_key=%s, ошибка=%s",
                link_key, e, extra={"user_id": "system"}
            )
            raise
