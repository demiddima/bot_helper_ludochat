# services/db_api/chats.py
from __future__ import annotations
import logging
from typing import Any, List, Dict

from .base import BaseApi

log = logging.getLogger(__name__)


class ChatsMixin(BaseApi):
    async def get_chats(self) -> List[Any]:
        try:
            r = await self.client.get("/chats/")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[get_chats] – user_id=system – Ошибка: %s", e, extra={"user_id": "system"})
            raise

    async def upsert_chat(self, chat_data: Dict) -> Dict:
        try:
            r = await self.client.post("/chats/", json=chat_data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            chat_id = chat_data.get("id", "system")
            log.error("[upsert_chat] – user_id=%s – Ошибка: %s", chat_id, e, extra={"user_id": chat_id})
            raise

    async def delete_chat(self, chat_id: int) -> None:
        try:
            r = await self.client.delete(f"/chats/{chat_id}")
            r.raise_for_status()
        except Exception as e:
            log.error("[delete_chat] – user_id=%s – Ошибка: %s", chat_id, e, extra={"user_id": chat_id})
            raise
