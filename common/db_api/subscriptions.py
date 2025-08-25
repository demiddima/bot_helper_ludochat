# services/db_api/subscriptions.py
from __future__ import annotations
import logging

from .base import BaseApi

log = logging.getLogger(__name__)


class SubscriptionsMixin(BaseApi):
    async def get_user_subscriptions(self, user_id: int) -> dict:
        try:
            r = await self.client.get(f"/subscriptions/{user_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Подписки: ошибка получения — user_id=%s, ошибка=%s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def put_user_subscriptions(
        self,
        user_id: int,
        news_enabled: bool,
        meetings_enabled: bool,
        important_enabled: bool,
    ) -> dict:
        try:
            payload = {
                "news_enabled": news_enabled,
                "meetings_enabled": meetings_enabled,
                "important_enabled": important_enabled,
            }
            r = await self.client.put(f"/subscriptions/{user_id}", json=payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Подписки: ошибка сохранения — user_id=%s, news=%s, meetings=%s, important=%s, ошибка=%s",
                user_id, news_enabled, meetings_enabled, important_enabled, e,
                extra={"user_id": user_id}
            )
            raise

    async def toggle_user_subscription(self, user_id: int, kind: str) -> dict:
        try:
            r = await self.client.post(f"/subscriptions/{user_id}/toggle", json={"kind": kind})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Подписки: ошибка переключения — user_id=%s, kind=%s, ошибка=%s",
                user_id, kind, e, extra={"user_id": user_id}
            )
            raise
    async def delete_user_subscriptions(self, user_id: int) -> None:
        try:
            r = await self.client.delete(f"/subscriptions/{user_id}")
            r.raise_for_status()
            log.info(
                "Подписки: удалены — user_id=%s",
                user_id, extra={"user_id": user_id}
            )
        except Exception as e:
            log.error(
                "Подписки: ошибка удаления — user_id=%s, ошибка=%s",
                user_id, e, extra={"user_id": user_id}
            )
            raise