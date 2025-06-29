from services.db_api_client import db_api_client
from tenacity import retry, stop_after_attempt, wait_fixed

RETRY = dict(stop=stop_after_attempt(5), wait=wait_fixed(3))

# USERS
@retry(**RETRY)
async def add_user(user_data):
    user_id = user_data.get("id")
    return await db_api_client.upsert_user(user_id, user_data)

@retry(**RETRY)
async def get_user(user_id):
    return await db_api_client.get_user(user_id)

@retry(**RETRY)
async def update_user(user_id, user_data):
    return await db_api_client.update_user(user_id, user_data)

@retry(**RETRY)
async def delete_user(user_id):
    await db_api_client.delete_user(user_id)

@retry(**RETRY)
async def has_terms_accepted(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user.get("terms_accepted"))

@retry(**RETRY)
async def set_terms_accepted(user_id: int) -> None:
    # Обновляем только поле terms_accepted
    await update_user(user_id, {"terms_accepted": True})

# CHATS
@retry(**RETRY)
async def upsert_chat(chat_data):
    return await db_api_client.upsert_chat(chat_data)

@retry(**RETRY)
async def get_chats():
    return await db_api_client.get_chats()

@retry(**RETRY)
async def delete_chat(chat_id):
    await db_api_client.delete_chat(chat_id)

# MEMBERSHIPS
@retry(**RETRY)
async def add_membership(user_id, chat_id):
    await db_api_client.add_membership(user_id, chat_id)

@retry(**RETRY)
async def remove_membership(user_id, chat_id):
    await db_api_client.remove_membership(user_id, chat_id)

# INVITE LINKS
@retry(**RETRY)
async def save_invite_link(user_id, chat_id, invite_link, created_at, expires_at):
    return await db_api_client.save_invite_link(user_id, chat_id, invite_link, created_at, expires_at)

@retry(**RETRY)
async def get_all_invite_links(user_id):
    return await db_api_client.get_all_invite_links(user_id)

@retry(**RETRY)
async def get_invite_links(user_id):
    return await db_api_client.get_invite_links(user_id)

@retry(**RETRY)
async def delete_invite_links(user_id):
    await db_api_client.delete_invite_links(user_id)

# ALGORITHM PROGRESS
@retry(**RETRY)
async def get_progress(user_id):
    return await db_api_client.get_progress(user_id)

@retry(**RETRY)
async def clear_progress(user_id):
    await db_api_client.clear_progress(user_id)

@retry(**RETRY)
async def set_progress(user_id, step):
    await db_api_client.set_progress(user_id, step)

@retry(**RETRY)
async def set_basic(user_id, completed):
    await db_api_client.set_basic(user_id, completed)

@retry(**RETRY)
async def set_advanced(user_id, completed):
    await db_api_client.set_advanced(user_id, completed)

@retry(**RETRY)
async def track_link_visit(link_key: str):
    return await db_api_client.track_link_visit(link_key)
