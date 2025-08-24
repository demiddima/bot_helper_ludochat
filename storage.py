import logging
from datetime import datetime
from common.db_api_client import db_api_client
from httpx import HTTPStatusError
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

log = logging.getLogger(__name__)

# Повторять любые исключения до 3 раз с интервалом 1 секунда
RETRY = {
    "retry": retry_if_exception_type(Exception),
    "stop": stop_after_attempt(3),
    "wait": wait_fixed(1),
}

# ===== USERS =====

@retry(**RETRY)
async def add_user(user_id: int, username: str | None, full_name: str | None) -> dict:
    return await db_api_client.upsert_user(user_id, username, full_name)


@retry(**RETRY)
async def get_user(user_id: int) -> dict:
    try:
        return await db_api_client.get_user(user_id)
    except HTTPStatusError as exc:
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
    except Exception:
        log.error(f"[STORAGE] has_terms_accepted failed for {user_id}", exc_info=True)
        return False


async def set_terms_accepted(user_id: int) -> None:
    try:
        await update_user(user_id, {"terms_accepted": True})
    except Exception:
        log.error(f"[STORAGE] set_terms_accepted failed for {user_id}", exc_info=True)


# ===== CHATS =====

@retry(**RETRY)
async def upsert_chat(chat_data: dict) -> dict:
    return await db_api_client.upsert_chat(chat_data)


@retry(**RETRY)
async def get_chats() -> list[dict]:
    return await db_api_client.get_chats()


@retry(**RETRY)
async def delete_chat(chat_id: int) -> None:
    await db_api_client.delete_chat(chat_id)


# ===== MEMBERSHIPS =====

@retry(**RETRY)
async def add_membership(user_id: int, chat_id: int) -> None:
    await db_api_client.add_membership(user_id, chat_id)


@retry(**RETRY)
async def remove_membership(user_id: int, chat_id: int) -> None:
    await db_api_client.remove_membership(user_id, chat_id)


# ===== INVITE LINKS =====

@retry(**RETRY)
async def save_invite_link(
    user_id: int,
    chat_id: int,
    invite_link: str,
    created_at: str,
    expires_at: str,
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


# ===== ALGORITHM PROGRESS =====

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


# ===== SUBSCRIPTIONS =====

DEFAULT_SUBS = {
    "news_enabled": False,
    "meetings_enabled": True,
    "important_enabled": True,
}

def _is_http_404(exc: Exception) -> bool:
    return (
        isinstance(exc, HTTPStatusError)
        and getattr(exc.response, "status_code", None) == 404
    )

@retry(**RETRY)
async def get_user_subscriptions(user_id: int) -> dict:
    func = "get_user_subscriptions"
    try:
        data = await db_api_client.get_user_subscriptions(user_id)
        log.info(f"[{func}] – user_id={user_id} – OK", extra={"user_id": user_id})
        return data
    except HTTPStatusError as exc:
        if _is_http_404(exc):
            log.info(f"[{func}] – user_id={user_id} – 404 Not Found", extra={"user_id": user_id})
            return {}
        raise


@retry(**RETRY)
async def ensure_user_subscriptions_defaults(user_id: int) -> dict:
    func = "ensure_user_subscriptions_defaults"
    data = await db_api_client.put_user_subscriptions(
        user_id=user_id,
        news_enabled=DEFAULT_SUBS["news_enabled"],
        meetings_enabled=DEFAULT_SUBS["meetings_enabled"],
        important_enabled=DEFAULT_SUBS["important_enabled"],
    )
    log.info(f"[{func}] – user_id={user_id} – OK", extra={"user_id": user_id})
    return data


@retry(**RETRY)
async def toggle_user_subscription(user_id: int, kind: str) -> dict:
    func = "toggle_user_subscription"
    try:
        data = await db_api_client.toggle_user_subscription(user_id, kind)
        log.info(f"[{func}] – user_id={user_id} – kind={kind} – OK", extra={"user_id": user_id})
        return data
    except HTTPStatusError as exc:
        if _is_http_404(exc):
            log.info(f"[{func}] – user_id={user_id} – 404 toggle ⇒ PUT defaults & retry", extra={"user_id": user_id})
            await ensure_user_subscriptions_defaults(user_id)
            data2 = await db_api_client.toggle_user_subscription(user_id, kind)
            log.info(f"[{func}] – user_id={user_id} – kind={kind} – OK(after create)", extra={"user_id": user_id})
            return data2
        raise
