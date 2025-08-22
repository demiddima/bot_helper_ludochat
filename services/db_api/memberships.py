# services/db_api/memberships.py
from __future__ import annotations
import logging
from typing import Any, List

from .base import BaseApi

log = logging.getLogger(__name__)


class MembershipsMixin(BaseApi):
    async def add_membership(self, user_id: int, chat_id: int) -> None:
        try:
            r = await self.client.post("/memberships/", params={"user_id": user_id, "chat_id": chat_id})
            r.raise_for_status()
        except Exception as e:
            log.error("[add_membership] – user_id=%s – Ошибка при добавлении в чат %s: %s", user_id, chat_id, e, extra={"user_id": user_id})
            raise

    async def remove_membership(self, user_id: int, chat_id: int) -> None:
        try:
            r = await self.client.delete("/memberships/", params={"user_id": user_id, "chat_id": chat_id})
            r.raise_for_status()
        except Exception as e:
            log.error("[remove_membership] – user_id=%s – Ошибка при удалении из чата %s: %s", user_id, chat_id, e, extra={"user_id": user_id})
            raise

    async def get_memberships(self, user_id: int, chat_id: int) -> List[Any]:
        try:
            r = await self.client.get("/memberships/", params={"user_id": user_id, "chat_id": chat_id})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[get_memberships] – user_id=%s – Ошибка при получении подписки на чат %s: %s", user_id, chat_id, e, extra={"user_id": user_id})
            raise

    async def list_memberships_by_chat(self, chat_id: int) -> List[dict]:
        try:
            r = await self.client.get("/memberships/", params={"chat_id": chat_id})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[list_memberships_by_chat] chat_id=%s – Ошибка: %s", chat_id, e)
            raise
