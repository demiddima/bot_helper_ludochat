# db_api_client.py
# Обновлён: Логирование всех ошибок в корпоративном формате с поддержкой user_id и отправкой в Telegram через handler

import httpx
from typing import Optional, Any, List
from config import DB_API_URL, API_KEY_VALUE
import logging

logging.getLogger("httpx").setLevel(logging.WARNING)

class DBApiClient:
    def __init__(self, api_url: Optional[str] = None):
        self.api_url = api_url or DB_API_URL.rstrip('/')
        self.client = httpx.AsyncClient(
            base_url=self.api_url,
            timeout=10,
            headers={"X-API-KEY": API_KEY_VALUE}
        )

    # USERS
    async def upsert_user(self, user_id: int, username: str, full_name: str) -> dict:
        try:
            r = await self.client.put(
                f"/users/{user_id}/upsert",
                json={
                    "username": username,
                    "full_name": full_name
                }
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.error(f"[upsert_user] – user_id={user_id} – Ошибка: {e}")
            raise

    async def get_user(self, user_id: int) -> dict:
        try:
            r = await self.client.get(f"/users/{user_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.error(
                "[get_user] – user_id=%s – Ошибка при получении пользователя: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def update_user(self, user_id: int, user_data: dict) -> dict:
        try:
            r = await self.client.put(f"/users/{user_id}", json=user_data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.error(
                "[update_user] – user_id=%s – Ошибка при обновлении пользователя: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def delete_user(self, user_id: int):
        try:
            r = await self.client.delete(f"/users/{user_id}")
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[delete_user] – user_id=%s – Ошибка при удалении пользователя: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    # CHATS
    async def get_chats(self) -> List[Any]:
        try:
            r = await self.client.get("/chats/")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.error(
                "[get_chats] – user_id=system – Ошибка при получении чатов: %s",
                e, extra={"user_id": "system"}
            )
            raise

    async def upsert_chat(self, chat_data: dict) -> dict:
        try:
            r = await self.client.post("/chats/", json=chat_data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            chat_id = chat_data.get("id", "system")
            logging.error(
                "[upsert_chat] – user_id=%s – Ошибка при upsert чата: %s",
                chat_id, e, extra={"user_id": chat_id}
            )
            raise

    async def delete_chat(self, chat_id: int):
        try:
            r = await self.client.delete(f"/chats/{chat_id}")
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[delete_chat] – user_id=%s – Ошибка при удалении чата: %s",
                chat_id, e, extra={"user_id": chat_id}
            )
            raise

    # MEMBERSHIPS
    async def add_membership(self, user_id: int, chat_id: int):
        try:
            r = await self.client.post(
                "/memberships/", params={"user_id": user_id, "chat_id": chat_id}
            )
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[add_membership] – user_id=%s – Ошибка при добавлении подписки на чат %s: %s",
                user_id, chat_id, e, extra={"user_id": user_id}
            )
            raise

    async def remove_membership(self, user_id: int, chat_id: int):
        try:
            r = await self.client.delete(
                "/memberships/", params={"user_id": user_id, "chat_id": chat_id}
            )
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[remove_membership] – user_id=%s – Ошибка при удалении подписки на чат %s: %s",
                user_id, chat_id, e, extra={"user_id": user_id}
            )
            raise

    async def get_memberships(self, user_id: int, chat_id: int) -> List[Any]:
        try:
            r = await self.client.get(
                "/memberships/",
                params={"user_id": user_id, "chat_id": chat_id}
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.error(
                "[get_memberships] – user_id=%s – Ошибка при получении подписки на чат %s: %s",
                user_id, chat_id, e, extra={"user_id": user_id}
            )
            raise

    # INVITE LINKS
    async def save_invite_link(
        self, user_id: int, chat_id: int, invite_link: str, created_at: str, expires_at: str
    ) -> dict:
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
            logging.error(
                "[save_invite_link] – user_id=%s – Ошибка при сохранении ссылки: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def get_all_invite_links(self, user_id):
        try:
            r = await self.client.get(f"/invite_links/all/{user_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.error(
                "[get_all_invite_links] – user_id=%s – Ошибка при получении ссылок: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def delete_invite_links(self, user_id: int):
        try:
            r = await self.client.delete(f"/invite_links/{user_id}")
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[delete_invite_links] – user_id=%s – Ошибка при удалении ссылок: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    # ALGORITHM PROGRESS
    async def get_progress(self, user_id: int) -> dict:
        try:
            r = await self.client.get(f"/algo/{user_id}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.error(
                "[get_progress] – user_id=%s – Ошибка при получении прогресса: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def clear_progress(self, user_id: int):
        try:
            r = await self.client.delete(f"/algo/{user_id}")
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[clear_progress] – user_id=%s – Ошибка при очистке прогресса: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def set_progress(self, user_id: int, step: int):
        try:
            r = await self.client.put(
                f"/algo/{user_id}/step", params={"step": step}
            )
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[set_progress] – user_id=%s – Ошибка при обновлении шага: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def set_basic(self, user_id: int, completed: bool):
        try:
            r = await self.client.put(
                f"/algo/{user_id}/basic", params={"completed": completed}
            )
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[set_basic] – user_id=%s – Ошибка при отметке базового шага: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    async def set_advanced(self, user_id: int, completed: bool):
        try:
            r = await self.client.put(
                f"/algo/{user_id}/advanced", params={"completed": completed}
            )
            r.raise_for_status()
        except Exception as e:
            logging.error(
                "[set_advanced] – user_id=%s – Ошибка при отметке расширенного шага: %s",
                user_id, e, extra={"user_id": user_id}
            )
            raise

    # Новый метод для подсчёта визитов по ссылке
    async def track_link_visit(self, link_key: str) -> dict:
        try:
            r = await self.client.post(
                "/links/visit",
                json={"link_key": link_key}
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logging.error(
                "[track_link_visit] – user_id=system – Ошибка при трекинге визита по ссылке: %s",
                e, extra={"user_id": "system"}
            )
            raise

    async def close(self):
        try:
            await self.client.aclose()
        except Exception as e:
            logging.error(
                "[close] – user_id=system – Ошибка при закрытии клиента: %s",
                e, extra={"user_id": "system"}
            )
            raise

# Экземпляр клиента для использования в проекте
db_api_client = DBApiClient()
