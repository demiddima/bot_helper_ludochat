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

    async def list_memberships_by_chat(
            self,
            chat_id: int,
            *,
            limit: int | None = None,
            offset: int | None = None,
        ) -> List[dict]:
            """
            Список мемберств по chat_id. Параметры пагинации опциональны.
            Бэк может игнорировать их — это ок.
            """
            try:
                params: dict[str, Any] = {"chat_id": chat_id}
                if limit is not None:
                    params["limit"] = int(limit)
                if offset is not None:
                    params["offset"] = int(offset)

                r = await self.client.get("/memberships/", params=params)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                log.error(
                    "Подписка: ошибка списка по чату — chat_id=%s, limit=%s, offset=%s, ошибка=%s",
                    chat_id, limit, offset, e, extra={"user_id": None}
                )
                raise
