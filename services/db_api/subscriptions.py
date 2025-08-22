# services/db_api/subscriptions.py
from __future__ import annotations
import logging

from .base import BaseApi

log = logging.getLogger(__name__)


class SubscriptionsMixin(BaseApi):
    async def get_user_subscriptions(self, user_id: int) -> dict:
        func = "get_user_subscriptions"
        try:
            r = await self.client.get(f"/subscriptions/{user_id}")
            r.raise_for_status()
            data = r.json()
            log.info("[%s] – user_id=%s – OK", func, user_id, extra={"user_id": user_id})
            return data
        except Exception as e:
            log.error("[%s] – user_id=%s – Ошибка: %s", func, user_id, e, extra={"user_id": user_id})
            raise

    async def put_user_subscriptions(
        self,
        user_id: int,
        news_enabled: bool,
        meetings_enabled: bool,
        important_enabled: bool,
    ) -> dict:
        func = "put_user_subscriptions"
        try:
            payload = {
                "news_enabled": news_enabled,
                "meetings_enabled": meetings_enabled,
                "important_enabled": important_enabled,
            }
            r = await self.client.put(f"/subscriptions/{user_id}", json=payload)
            r.raise_for_status()
            data = r.json()
            log.info("[%s] – user_id=%s – OK", func, user_id, extra={"user_id": user_id})
            return data
        except Exception as e:
            log.error("[%s] – user_id=%s – Ошибка upsert: %s", func, user_id, e, extra={"user_id": user_id})
            raise

    async def toggle_user_subscription(self, user_id: int, kind: str) -> dict:
        func = "toggle_user_subscription"
        try:
            r = await self.client.post(f"/subscriptions/{user_id}/toggle", json={"kind": kind})
            r.raise_for_status()
            data = r.json()
            log.info("[%s] – user_id=%s – kind=%s – OK", func, user_id, kind, extra={"user_id": user_id})
            return data
        except Exception as e:
            log.error("[%s] – user_id=%s – Ошибка toggle '%s': %s", func, user_id, kind, e, extra={"user_id": user_id})
            raise
