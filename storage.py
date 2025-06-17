from services.db_api_client import db_api_client

# USERS
async def add_user(user_data):
    user_id = user_data.get("id")
    return await db_api_client.upsert_user(user_id, user_data)

async def get_user(user_id):
    return await db_api_client.get_user(user_id)

async def update_user(user_id, user_data):
    return await db_api_client.update_user(user_id, user_data)

async def delete_user(user_id):
    await db_api_client.delete_user(user_id)

# CHATS
async def get_chats():
    return await db_api_client.get_chats()

async def upsert_chat(chat_data):
    return await db_api_client.upsert_chat(chat_data)

async def delete_chat(chat_id):
    await db_api_client.delete_chat(chat_id)

# MEMBERSHIPS
async def add_membership(user_id, chat_id):
    await db_api_client.add_membership(user_id, chat_id)

async def remove_membership(user_id, chat_id):
    await db_api_client.remove_membership(user_id, chat_id)

# INVITE LINKS
async def save_invite_link(user_id, chat_id, invite_link, created_at, expires_at):
    return await db_api_client.save_invite_link(user_id, chat_id, invite_link, created_at, expires_at)

async def get_invite_links(user_id):
    return await db_api_client.get_invite_links(user_id)

async def delete_invite_links(user_id):
    await db_api_client.delete_invite_links(user_id)

# ALGORITHM PROGRESS
async def get_progress(user_id):
    return await db_api_client.get_progress(user_id)

async def clear_progress(user_id):
    await db_api_client.clear_progress(user_id)

async def set_progress(user_id, step):
    await db_api_client.set_progress(user_id, step)

async def set_basic(user_id, completed):
    await db_api_client.set_basic(user_id, completed)

async def set_advanced(user_id, completed):
    await db_api_client.set_advanced(user_id, completed)
