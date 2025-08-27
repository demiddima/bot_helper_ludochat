# services/db_api/broadcasts.py
# Коммит: refactor(db_api): заменить scheduled_at → schedule, добавить enabled и фильтры списка
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
        schedule: Optional[str] = None,  # "27.08.2025 15:00" или "0 15 * * 1"
        enabled: Optional[bool] = None,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"kind": kind, "title": title, "content": content}
        if status is not None:
            payload["status"] = status
        if schedule is not None:
            payload["schedule"] = schedule
        if enabled is not None:
            payload["enabled"] = bool(enabled)
        if created_by is not None:
            payload["created_by"] = created_by
        try:
            r = await self.client.post("/broadcasts", json=payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Рассылки: ошибка создания — kind=%s, title=%s, status=%s, schedule=%s, enabled=%s, ошибка=%s",
                kind, title, status, schedule, enabled, e,
                extra={"user_id": created_by or None},
            )
            raise

    async def get_broadcast(self, broadcast_id: int) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"/broadcasts/{broadcast_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка получения — id=%s, ошибка=%s", broadcast_id, e)
            raise

    async def list_broadcasts(
        self,
        *,
        status: Optional[str] = None,
        enabled: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if enabled is not None:
            params["enabled"] = bool(enabled)
        try:
            r = await self.client.get("/broadcasts", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(
                "Рассылки: ошибка списка — status=%s, enabled=%s, limit=%s, offset=%s, ошибка=%s",
                status, enabled, limit, offset, e,
            )
            raise

    async def update_broadcast(
        self,
        broadcast_id: int,
        *,
        kind: Optional[str] = None,
        title: Optional[str] = None,
        content: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        schedule: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if kind is not None:
            data["kind"] = kind
        if title is not None:
            data["title"] = title
        if content is not None:
            data["content"] = content
        if status is not None:
            data["status"] = status
        if schedule is not None:
            data["schedule"] = schedule
        if enabled is not None:
            data["enabled"] = bool(enabled)

        try:
            r = await self.client.patch(f"/broadcasts/{broadcast_id}", json=data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка обновления — id=%s, ошибка=%s", broadcast_id, e)
            raise

    async def delete_broadcast(self, broadcast_id: int) -> None:
        try:
            r = await self.client.delete(f"/broadcasts/{broadcast_id}")
            r.raise_for_status()
        except Exception as e:
            log.error("Рассылки: ошибка удаления — id=%s, ошибка=%s", broadcast_id, e)
            raise

    # -------- target --------
    async def get_broadcast_target(self, broadcast_id: int) -> Dict[str, Any]:
        try:
            r = await self.client.get(f"/broadcasts/{broadcast_id}/target")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка получения таргета — id=%s, ошибка=%s", broadcast_id, e)
            raise

    async def put_broadcast_target(self, broadcast_id: int, target_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = await self.client.put(f"/broadcasts/{broadcast_id}/target", json=target_payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Рассылки: ошибка сохранения таргета — id=%s, ошибка=%s", broadcast_id, e)
            raise

    # -------- audience --------
    async def audience_preview(self, target_payload: Dict[str, Any], limit: int = 10000) -> Dict[str, Any]:
        try:
            r = await self.client.post("/audiences/preview", json={"target": target_payload, "limit": limit})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Аудитория: ошибка предпросмотра — тип=%s, лимит=%s, ошибка=%s", target_payload.get("type"), limit, e)
            raise

    async def audiences_resolve(self, target_payload: Dict[str, Any], limit: Optional[int] = None) -> Dict[str, Any]:
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
            log.error("Рассылки: ошибка немедленной отправки — id=%s, ошибка=%s", broadcast_id, e)
            raise

    # -------- deliveries --------
    async def list_deliveries(self, broadcast_id: int, status: Optional[str] = None, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        try:
            r = await self.client.get(f"/broadcasts/{broadcast_id}/deliveries", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Доставки: ошибка списка — id=%s, status=%s, limit=%s, offset=%s, ошибка=%s", broadcast_id, status, limit, offset, e)
            raise

    async def deliveries_materialize(self, broadcast_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            r = await self.client.post(f"/broadcasts/{broadcast_id}/deliveries/materialize", json=payload)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Доставки: ошибка materialize — id=%s, ошибка=%s", broadcast_id, e)
            raise

    async def deliveries_report(self, broadcast_id: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            r = await self.client.post(f"/broadcasts/{broadcast_id}/deliveries/report", json={"items": items})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error("Доставки: ошибка report — id=%s, ошибка=%s", broadcast_id, e)
            raise

    # -------- helpers --------
    async def toggle_enabled(self, broadcast_id: int, enabled: bool) -> Dict[str, Any]:
        return await self.update_broadcast(broadcast_id, enabled=enabled)

    async def set_schedule(self, broadcast_id: int, schedule: Optional[str]) -> Dict[str, Any]:
        return await self.update_broadcast(broadcast_id, schedule=schedule)
