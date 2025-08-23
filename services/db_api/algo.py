# services/db_api/algo.py
from __future__ import annotations
import logging

from .base import BaseApi

log = logging.getLogger(__name__)


class AlgoMixin(BaseApi):
    async def get_progress(self, user_id: int) -> dict:
        try:
            r = await self.client.get(f"/algo/{user_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Алгоритм: ошибка получения прогресса — user_id=%s, ошибка=%s", user_id, e, extra={"user_id": user_id})
            raise

    async def clear_progress(self, user_id: int) -> None:
        try:
            r = await self.client.delete(f"/algo/{user_id}")
            r.raise_for_status()
        except Exception as e:
            log.error("Алгоритм: ошибка очистки прогресса — user_id=%s, ошибка=%s", user_id, e, extra={"user_id": user_id})
            raise

    async def set_progress(self, user_id: int, step: int) -> None:
        try:
            r = await self.client.put(f"/algo/{user_id}/step", params={"step": step})
            r.raise_for_status()
        except Exception as e:
            log.error("Алгоритм: ошибка установки шага — user_id=%s, step=%s, ошибка=%s", user_id, step, e, extra={"user_id": user_id})
            raise

    async def set_basic(self, user_id: int, completed: bool) -> None:
        try:
            r = await self.client.put(f"/algo/{user_id}/basic", params={"completed": completed})
            r.raise_for_status()
        except Exception as e:
            log.error("Алгоритм: ошибка отметки basic — user_id=%s, completed=%s, ошибка=%s", user_id, completed, e, extra={"user_id": user_id})
            raise

    async def set_advanced(self, user_id: int, completed: bool) -> None:
        try:
            r = await self.client.put(f"/algo/{user_id}/advanced", params={"completed": completed})
            r.raise_for_status()
        except Exception as e:
            log.error("Алгоритм: ошибка отметки advanced — user_id=%s, completed=%s, ошибка=%s", user_id, completed, e, extra={"user_id": user_id})
            raise
