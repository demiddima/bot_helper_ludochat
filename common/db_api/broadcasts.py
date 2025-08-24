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
        content: Dict[str, Any],  # {"text": "<HTML>", "files": "id1,id2"}
        status: Optional[str] = None,
        scheduled_at: Optional[str] = None,  # "YYYY-MM-DD HH:MM:SS" (МСК-naive)
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"kind": kind, "title": title, "content": content}
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
            log.error(
                "Рассылки: ошибка создания — kind=%s, title=%s, статус=%s, время=%s, ошибка=%s",
                kind, title, status, scheduled_at, e, extra={"user_id": created_by or None}
            )
            raise

    async def get_broadcast(self, broadcast_id: int) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"/broadcasts/{broadcast_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка получения — id=%s, ошибка=%s", broadcast_id, e, extra={"user_id": None})
            raise

    async def list_broadcasts(self, *, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        try:
            r = await self.client.get("/broadcasts", params={"limit": limit, "offset": offset})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка списка — limit=%s, offset=%s, ошибка=%s", limit, offset, e, extra={"user_id": None})
            raise

    async def update_broadcast(self, broadcast_id: int, **patch: object) -> Dict[str, Any]:
        try:
            data = {k: v for k, v in patch.items() if v is not None}
            r = await self.client.patch(f"/broadcasts/{broadcast_id}", json=data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка обновления — id=%s, ошибка=%s", broadcast_id, e, extra={"user_id": None})
            raise

    async def delete_broadcast(self, broadcast_id: int) -> None:
        try:
            r = await self.client.delete(f"/broadcasts/{broadcast_id}")
            r.raise_for_status()
        except Exception as e:
            log.error("Рассылки: ошибка удаления — id=%s, ошибка=%s", broadcast_id, e, extra={"user_id": None})
            raise

    # -------- target --------
    async def get_broadcast_target(self, broadcast_id: int) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"/broadcasts/{broadcast_id}/target")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка получения таргета — id=%s, ошибка=%s", broadcast_id, e, extra={"user_id": None})
            raise

    async def put_broadcast_target(self, broadcast_id: int, target_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        target_payload:
          {"type":"ids","user_ids":[...]}
          {"type":"sql","sql":"SELECT ..."}
          {"type":"kind","kind":"news|meetings|important"}
        """
        try:
            r = await self.client.put(f"/broadcasts/{broadcast_id}/target", json=target_payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка сохранения таргета — id=%s, ошибка=%s", broadcast_id, e, extra={"user_id": None})
            raise

    # -------- audience --------
    async def audience_preview(self, target_payload: Dict[str, Any], limit: int = 10000) -> Dict[str, Any]:
        """
        POST /audiences/preview {target, limit} -> {"total": int, "sample": [ids]}
        """
        try:
            r = await self.client.post("/audiences/preview", json={"target": target_payload, "limit": limit})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Аудитория: ошибка предпросмотра — тип=%s, лимит=%s, ошибка=%s",
                target_payload.get("type"), limit, e, extra={"user_id": None}
            )
            raise

    async def audiences_resolve(self, target_payload: Dict[str, Any], limit: Optional[int] = None) -> Dict[str, Any]:
        """
        POST /audiences/resolve
        body: {"target": <target_payload>, "limit": <int>}  # если limit не None
        -> {"total": int, "ids": [int,...]}
        """
        payload: Dict[str, Any] = {"target": target_payload}
        if limit is not None:
            payload["limit"] = int(limit)
        r = await self.client.post("/audiences/resolve", json=payload)
        r.raise_for_status()
        return r.json()

    # -------- sending --------
    async def send_broadcast_now(self, broadcast_id: int) -> Dict[str, Any]:
        try:
            r = await self.client.post(f"/broadcasts/{broadcast_id}/send_now")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка немедленной отправки — id=%s, ошибка=%s", broadcast_id, e, extra={"user_id": None})
            raise

    # -------- deliveries --------
    async def list_deliveries(self, broadcast_id: int, status: Optional[str] = None, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        try:
            params = {"limit": limit, "offset": offset}
            if status:
                params["status"] = status
            r = await self.client.get(f"/broadcasts/{broadcast_id}/deliveries", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Рассылки: ошибка списка доставок — id=%s, status=%s, limit=%s, offset=%s, ошибка=%s",
                broadcast_id, status, limit, offset, e, extra={"user_id": None}
            )
            raise

    async def deliveries_materialize(self, broadcast_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        POST /broadcasts/{id}/deliveries/materialize
        payload = {"ids":[...]} ИЛИ {"target": {...}}, "limit": N
        -> {"total": int, "created": int, "existed": int}
        """
        try:
            r = await self.client.post(f"/broadcasts/{broadcast_id}/deliveries/materialize", json=payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Доставки: ошибка materialize — id=%s, payload_keys=%s, ошибка=%s",
                broadcast_id, sorted(list(payload.keys())) if isinstance(payload, dict) else "n/a",
                e, extra={"user_id": None}
            )
            raise

    async def deliveries_report(self, broadcast_id: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        POST /broadcasts/{id}/deliveries/report
        payload = {"items":[{"user_id":..., "status":"sent|failed|skipped|pending",
                             "message_id":?, "error_code":?, "error_message":?, "sent_at":?, "attempt_inc":1}, ...]}
        -> {"processed": int, "updated": int, "inserted": int}
        """
        try:
            r = await self.client.post(f"/broadcasts/{broadcast_id}/deliveries/report", json={"items": items})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Доставки: ошибка report — id=%s, batch=%s, ошибка=%s",
                broadcast_id, len(items) if isinstance(items, list) else "n/a",
                e, extra={"user_id": None}
            )
            raise
