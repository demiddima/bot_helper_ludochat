# services/db_api/broadcasts.py
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from .base import BaseApi

log = logging.getLogger(__name__)


class BroadcastsMixin(BaseApi):
    async def create_broadcast(
        self,
        *,
        kind: str,
        title: str,
        content_html: str,
        status: Optional[str] = None,
        scheduled_at: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"kind": kind, "title": title, "content_html": content_html}
        if status is not None:
            payload["status"] = status
        if scheduled_at is not None:
            payload["scheduled_at"] = scheduled_at
        if created_by is not None:
            payload["created_by"] = created_by
        try:
            r = await self.client.post("/broadcasts", json=payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[create_broadcast] – Ошибка: %s", e)
            raise

    async def get_broadcast(self, broadcast_id: int) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"/broadcasts/{broadcast_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[get_broadcast] – id=%s – Ошибка: %s", broadcast_id, e)
            raise

    async def list_broadcasts(self, *, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        try:
            r = await self.client.get("/broadcasts", params={"limit": limit, "offset": offset})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[list_broadcasts] – Ошибка: %s", e)
            raise

    async def update_broadcast(self, broadcast_id: int, **patch: object) -> Dict[str, Any]:
        try:
            data = {k: v for k, v in patch.items() if v is not None}
            r = await self.client.patch(f"/broadcasts/{broadcast_id}", json=data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[update_broadcast] – id=%s – Ошибка: %s", broadcast_id, e)
            raise

    async def delete_broadcast(self, broadcast_id: int) -> None:
        try:
            r = await self.client.delete(f"/broadcasts/{broadcast_id}")
            r.raise_for_status()
        except Exception as e:
            log.error("[delete_broadcast] – id=%s – Ошибка: %s", broadcast_id, e)
            raise

    # -------- memberships helper --------
    async def list_memberships_by_chat(self, chat_id: int) -> List[Dict[str, Any]]:
        try:
            r = await self.client.get("/memberships/", params={"chat_id": chat_id})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[list_memberships_by_chat] chat_id=%s – Ошибка: %s", chat_id, e)
            raise

    # -------- target/media/sending --------
    async def get_broadcast_target(self, broadcast_id: int) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"/broadcasts/{broadcast_id}/target")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[get_broadcast_target] id=%s – Ошибка: %s", broadcast_id, e)
            raise

    async def put_broadcast_target(self, broadcast_id: int, target_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = await self.client.put(f"/broadcasts/{broadcast_id}/target", json=target_payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[put_broadcast_target] id=%s – Ошибка: %s", broadcast_id, e)
            raise

    async def get_broadcast_media(self, broadcast_id: int) -> List[Dict[str, Any]]:
        try:
            r = await self.client.get(f"/broadcasts/{broadcast_id}/media")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[get_broadcast_media] id=%s – Ошибка: %s", broadcast_id, e)
            raise

    async def put_broadcast_media(self, broadcast_id: int, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        try:
            r = await self.client.put(f"/broadcasts/{broadcast_id}/media", json={"items": items})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[put_broadcast_media] id=%s – Ошибка: %s", broadcast_id, e)
            raise

    async def audience_preview(self, target_payload: Dict[str, Any], limit: int = 10000) -> Dict[str, Any]:
        try:
            r = await self.client.post("/audiences/preview", json={"target": target_payload, "limit": limit})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[audience_preview] – Ошибка: %s", e)
            raise

    async def send_broadcast_now(self, broadcast_id: int) -> Dict[str, Any]:
        try:
            r = await self.client.post(f"/broadcasts/{broadcast_id}/send_now")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[send_broadcast_now] id=%s – Ошибка: %s", broadcast_id, e)
            raise

    async def list_deliveries(self, broadcast_id: int, status: Optional[str] = None, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        try:
            params = {"limit": limit, "offset": offset}
            if status:
                params["status"] = status
            r = await self.client.get(f"/broadcasts/{broadcast_id}/deliveries", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("[list_deliveries] id=%s – Ошибка: %s", broadcast_id, e)
            raise
