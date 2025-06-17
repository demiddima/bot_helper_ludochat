import httpx
from typing import Optional, Any, List

from config import DB_API_URL

class DBApiClient:
    def __init__(self, api_url: Optional[str] = None):
        self.api_url = api_url or DB_API_URL
        self.client = httpx.AsyncClient(base_url=self.api_url, timeout=10)
    
    # USERS
    async def upsert_user(self, user_id: int, user_data: dict) -> dict:
        r = await self.client.put(f"/users/{user_id}/upsert", json=user_data)
        r.raise_for_status()
        return r.json() 

    async def get_user(self, user_id: int) -> dict:
        r = await self.client.get(f"/users/{user_id}")
        r.raise_for_status()
        return r.json()

    async def update_user(self, user_id: int, user_data: dict) -> dict:
        r = await self.client.put(f"/users/{user_id}", json=user_data)
        r.raise_for_status()
        return r.json()

    async def delete_user(self, user_id: int):
        r = await self.client.delete(f"/users/{user_id}")
        r.raise_for_status()

    # CHATS
    async def get_chats(self) -> List[Any]:
        r = await self.client.get("/chats/")
        r.raise_for_status()
        return r.json()

    async def upsert_chat(self, chat_data: dict) -> dict:
        r = await self.client.post("/chats/", json=chat_data)
        r.raise_for_status()
        return r.json()

    async def delete_chat(self, chat_id: int):
        r = await self.client.delete(f"/chats/{chat_id}")
        r.raise_for_status()

    # MEMBERSHIPS
    async def add_membership(self, user_id: int, chat_id: int):
        r = await self.client.post("/memberships/", params={"user_id": user_id, "chat_id": chat_id})
        r.raise_for_status()

    async def remove_membership(self, user_id: int, chat_id: int):
        r = await self.client.delete("/memberships/", params={"user_id": user_id, "chat_id": chat_id})
        r.raise_for_status()

    # INVITE LINKS
    async def save_invite_link(self, user_id: int, chat_id: int, invite_link: str, created_at: str, expires_at: str) -> dict:
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

    async def get_invite_links(self, user_id: int) -> list:
        r = await self.client.get(f"/invite_links/{user_id}")
        r.raise_for_status()
        return r.json()

    async def delete_invite_links(self, user_id: int):
        r = await self.client.delete(f"/invite_links/{user_id}")
        r.raise_for_status()

    # ALGORITHM PROGRESS
    async def get_progress(self, user_id: int) -> dict:
        r = await self.client.get(f"/algo/{user_id}")
        r.raise_for_status()
        return r.json()

    async def clear_progress(self, user_id: int):
        r = await self.client.delete(f"/algo/{user_id}")
        r.raise_for_status()

    async def set_progress(self, user_id: int, step: int):
        r = await self.client.put(f"/algo/{user_id}/step", params={"step": step})
        r.raise_for_status()

    async def set_basic(self, user_id: int, completed: bool):
        r = await self.client.put(f"/algo/{user_id}/basic", params={"completed": completed})
        r.raise_for_status()

    async def set_advanced(self, user_id: int, completed: bool):
        r = await self.client.put(f"/algo/{user_id}/advanced", params={"completed": completed})
        r.raise_for_status()

    async def close(self):
        await self.client.aclose()

db_api_client = DBApiClient()
