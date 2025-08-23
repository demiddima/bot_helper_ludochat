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
            log.error(
                "Подписка: ошибка добавления — user_id=%s, chat_id=%s, ошибка=%s",
                user_id, chat_id, e, extra={"user_id": user_id}
            )
            raise

    async def remove_membership(self, user_id: int, chat_id: int) -> None:
        try:
            r = await self.client.delete("/memberships/", params={"user_id": user_id, "chat_id": chat_id})
            r.raise_for_status()
        except Exception as e:
            log.error(
                "Подписка: ошибка удаления — user_id=%s, chat_id=%s, ошибка=%s",
                user_id, chat_id, e, extra={"user_id": user_id}
            )
            raise

    async def get_memberships(self, user_id: int, chat_id: int) -> List[Any]:
        try:
            r = await self.client.get("/memberships/", params={"user_id": user_id, "chat_id": chat_id})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Подписка: ошибка получения — user_id=%s, chat_id=%s, ошибка=%s",
                user_id, chat_id, e, extra={"user_id": user_id}
            )
            raise

    async def list_memberships_by_chat(self, chat_id: int) -> List[dict]:
        try:
            r = await self.client.get("/memberships/", params={"chat_id": chat_id})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            # user_id неизвестен для агрегата по чату — ставим None
            log.error(
                "Подписка: ошибка списка по чату — chat_id=%s, ошибка=%s",
                chat_id, e, extra={"user_id": None}
            )
            raise
