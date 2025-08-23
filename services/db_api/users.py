# services/db_api/users.py
from __future__ import annotations
import logging
from typing import Dict

from .base import BaseApi

log = logging.getLogger(__name__)


class UsersMixin(BaseApi):
    async def upsert_user(self, user_id: int, username: str, full_name: str) -> Dict:
        try:
            r = await self.client.put(
                f"/users/{user_id}/upsert",
                json={"username": username, "full_name": full_name},
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Пользователь: ошибка сохранения — user_id=%s, username=%s, ошибка=%s",
                user_id, username, e, extra={"user_id": user_id}
            )
            raise

    async def get_user(self, user_id: int) -> Dict:
        try:
            r = await self.client.get(f"/users/{user_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Пользователь: ошибка получения — user_id=%s, ошибка=%s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def update_user(self, user_id: int, user_data: Dict) -> Dict:
        try:
            r = await self.client.put(f"/users/{user_id}", json=user_data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Пользователь: ошибка обновления — user_id=%s, ошибка=%s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def delete_user(self, user_id: int) -> None:
        try:
            r = await self.client.delete(f"/users/{user_id}")
            r.raise_for_status()
        except Exception as e:
            log.error(
                "Пользователь: ошибка удаления — user_id=%s, ошибка=%s",
                user_id, e, extra={"user_id": user_id}
            )
            raise
