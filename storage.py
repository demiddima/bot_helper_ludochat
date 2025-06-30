import logging
from services.db_api_client import db_api_client
from httpx import HTTPStatusError
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

# Повторять любые исключения до 3 раз с интервалом 1 секунда
RETRY = {
    "retry": retry_if_exception_type(Exception),
    "stop": stop_after_attempt(3),
    "wait": wait_fixed(1),
}

# USERS

@retry(**RETRY)
async def add_user(user_data: dict) -> dict:
    user_id = user_data.get("id")
    return await db_api_client.upsert_user(user_id, user_data)


@retry(**RETRY)
async def get_user(user_id: int) -> dict:
    try:
        return await db_api_client.get_user(user_id)
    except HTTPStatusError as exc:
        # если пользователя нет — возвращаем пустой dict
        if exc.response.status_code == 404:
            return {}
        raise


@retry(**RETRY)
async def update_user(user_id: int, user_data: dict) -> dict:
    return await db_api_client.update_user(user_id, user_data)


async def has_terms_accepted(user_id: int) -> bool:
    try:
        user = await get_user(user_id)
        return bool(user.get("terms_accepted"))
    except Exception as exc:
        logging.error(f"[STORAGE] has_terms_accepted failed for {user_id}: {exc}")
        return False


async def set_terms_accepted(user_id: int) -> None:
    try:
        # Обновляем только флаг terms_accepted
        await update_user(user_id, {"terms_accepted": True})
    except Exception as exc:
        logging.error(f"[STORAGE] set_terms_accepted failed for {user_id}: {exc}")


# CHATS

@retry(**RETRY)
async def upsert_chat(chat_data: dict) -> dict:
    return await db_api_client.upsert_chat(chat_data)


@retry(**RETRY)
async def get_chats() -> list[dict]:
    return await db_api_client.get_chats()


@retry(**RETRY)
async def delete_chat(chat_id: int) -> None:
    await db_api_client.delete_chat(chat_id)


# MEMBERSHIPS

@retry(**RETRY)
async def add_membership(user_id: int, chat_id: int) -> None:
    await db_api_client.add_membership(user_id, chat_id)


@retry(**RETRY)
async def remove_membership(user_id: int, chat_id: int) -> None:
    await db_api_client.remove_membership(user_id, chat_id)


# INVITE LINKS

@retry(**RETRY)
async def save_invite_link(
    user_id: int,
    chat_id: int,
    invite_link: str,
    created_at: str,
    expires_at: str
) -> dict:
    return await db_api_client.save_invite_link(
        user_id, chat_id, invite_link, created_at, expires_at
    )


@retry(**RETRY)
async def get_all_invite_links(user_id: int) -> list[dict]:
    return await db_api_client.get_all_invite_links(user_id)


@retry(**RETRY)
async def track_link_visit(link_key: str) -> dict:
    return await db_api_client.track_link_visit(link_key)


# ALGORITHM PROGRESS

@retry(**RETRY)
async def get_progress(user_id: int) -> dict:
    return await db_api_client.get_progress(user_id)


@retry(**RETRY)
async def clear_progress(user_id: int) -> None:
    await db_api_client.clear_progress(user_id)


@retry(**RETRY)
async def set_progress(user_id: int, step: int) -> None:
    await db_api_client.set_progress(user_id, step)


@retry(**RETRY)
async def set_basic(user_id: int, completed: bool) -> None:
    await db_api_client.set_basic(user_id, completed)


@retry(**RETRY)
async def set_advanced(user_id: int, completed: bool) -> None:
    await db_api_client.set_advanced(user_id, completed)
