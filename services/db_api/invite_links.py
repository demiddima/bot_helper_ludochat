# services/db_api/invite_links.py
from __future__ import annotations
import logging
from typing import Dict

from .base import BaseApi

log = logging.getLogger(__name__)


class InviteLinksMixin(BaseApi):
    async def save_invite_link(self, user_id: int, chat_id: int, invite_link: str, created_at: str, expires_at: str) -> Dict:
        try:
            payload = {
                "user_id": user_id,
                "chat_id": chat_id,
                "invite_link": invite_link,
                "created_at": created_at,
                "expires_at": expires_at,
            }
            r = await self.client.post("/invite_links/", json=payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[save_invite_link] – user_id=%s – Ошибка: %s", user_id, e, extra={"user_id": user_id})
            raise

    async def get_all_invite_links(self, user_id: int) -> Dict:
        try:
            r = await self.client.get(f"/invite_links/all/{user_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[get_all_invite_links] – user_id=%s – Ошибка: %s", user_id, e, extra={"user_id": user_id})
            raise

    async def delete_invite_links(self, user_id: int) -> None:
        try:
            r = await self.client.delete(f"/invite_links/{user_id}")
            r.raise_for_status()
        except Exception as e:
            log.error("[delete_invite_links] – user_id=%s – Ошибка: %s", user_id, e, extra={"user_id": user_id})
            raise
