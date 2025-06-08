import logging
import aiomysql
from aiomysql import Pool
from typing import Optional
from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
from utils import log_and_report
from aiogram import Bot
from config import BOT_TOKEN, ERROR_LOG_CHANNEL_ID
from datetime import datetime, timedelta

pool: Optional[Pool] = None
bot = Bot(token=BOT_TOKEN)

async def init_db_pool() -> None:
    """
    Создаёт пул и гарантирует наличие всех трёх таблиц:
    - chats
    - user_memberships
    - invite_links
    """
    global pool
    if pool is not None:
        return
    try:
        pool = await aiomysql.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            autocommit=False,
            minsize=1,
            maxsize=5,
        )
        logging.info(f"[DB] Pool created: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    except Exception as e:
        await log_and_report(e, "init_db_pool")
        raise

    await init_tables()

async def init_tables() -> None:
    """
    CREATE TABLE IF NOT EXISTS для:
    - chats
    - user_memberships
    - invite_links
    """
    if pool is None:
        raise RuntimeError("init_db_pool() must be called before init_tables()")

    create_chats_sql = """
CREATE TABLE IF NOT EXISTS chats (
    id BIGINT PRIMARY KEY,
    title VARCHAR(256) NOT NULL,
    type ENUM('public_channel','supergroup','group','private_channel','bot') NOT NULL,
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"""
    create_memberships_sql = """
CREATE TABLE IF NOT EXISTS user_memberships (
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    username VARCHAR(255),
    full_name VARCHAR(255),
    joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, chat_id),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"""
    create_invite_links_sql = """
CREATE TABLE IF NOT EXISTS invite_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    invite_link VARCHAR(512) NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    UNIQUE KEY uniq_user_chat (user_id, chat_id),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"""

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(create_chats_sql)
            await cur.execute(create_memberships_sql)
            await cur.execute(create_invite_links_sql)
        await conn.commit()
    logging.info("[DB] Tables ensured")


# ------------------ CHATS CRUD ------------------

async def upsert_chat(chat_id: int, title: str, type_: str) -> None:
    """
    INSERT INTO chats или обновить title, если уже есть.
    """
    if pool is None:
        raise RuntimeError("init_db_pool() must be called before upsert_chat()")

    sql = """
INSERT INTO chats (id, title, type)
VALUES (%s, %s, %s)
ON DUPLICATE KEY UPDATE title = VALUES(title);
"""
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (chat_id, title, type_))
            await conn.commit()
        logging.info(f"[DB] upsert_chat: {chat_id}")
    except Exception as e:
        await log_and_report(e, f"upsert_chat({chat_id})")

async def delete_chat(chat_id: int) -> None:
    """
    DELETE FROM chats WHERE id = chat_id
    """
    if pool is None:
        raise RuntimeError("init_db_pool() must be called before delete_chat()")

    sql = "DELETE FROM chats WHERE id = %s;"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (chat_id,))
            await conn.commit()
        logging.info(f"[DB] delete_chat: {chat_id}")
    except Exception as e:
        await log_and_report(e, f"delete_chat({chat_id})")


# ------------ USER_MEMBERSHIPS CRUD ------------

async def add_user_to_chat(
    user_id: int,
    chat_id: int,
    username: str | None = None,
    full_name: str | None = None,
) -> None:
    """
    INSERT INTO user_memberships или обновить username/full_name, если запись есть.
    """
    if pool is None:
        raise RuntimeError("init_db_pool() must be called before add_user_to_chat()")

    sql = """
INSERT INTO user_memberships (user_id, chat_id, username, full_name)
VALUES (%s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    username = VALUES(username),
    full_name = VALUES(full_name),
    joined_at = CURRENT_TIMESTAMP;
"""
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    sql,
                    (user_id, chat_id, username or "", full_name or ""),
                )
            await conn.commit()
        logging.info(f"[DB] add_user_to_chat: {user_id}→{chat_id}")
    except Exception as e:
        await log_and_report(e, f"add_user_to_chat({user_id},{chat_id})")

async def remove_user_from_chat(user_id: int, chat_id: int) -> None:
    """
    DELETE FROM user_memberships WHERE user_id=... AND chat_id=...
    """
    if pool is None:
        raise RuntimeError("init_db_pool() must be called before remove_user_from_chat()")

    sql = "DELETE FROM user_memberships WHERE user_id=%s AND chat_id=%s;"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (user_id, chat_id))
            await conn.commit()
        logging.info(f"[DB] remove_user_from_chat: {user_id}←{chat_id}")
    except Exception as e:
        await log_and_report(e, f"remove_user_from_chat({user_id},{chat_id})")


# --------------- INVITE_LINKS CRUD ---------------

async def save_invite_link(user_id: int, chat_id: int, invite_link: str) -> None:
    """
    Сохраняет однодневную invite_link, перезаписывая старую (REPLACE).
    """
    if pool is None:
        raise RuntimeError("init_db_pool() must be called first")
    now = datetime.utcnow()
    expires = now + timedelta(days=1)
    sql = """
REPLACE INTO invite_links
    (user_id, chat_id, invite_link, created_at, expires_at)
VALUES (%s, %s, %s, %s, %s);
"""
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (user_id, chat_id, invite_link, now, expires))
            await conn.commit()
        logging.info(f"[DB] save_invite_link: {user_id}:{chat_id}")
    except Exception as e:
        await log_and_report(e, f"save_invite_link({user_id},{chat_id})")

async def get_valid_invite_links(user_id: int):
    """
    Возвращает список (chat_id, invite_link) для неистёкших записей.
    """
    if pool is None:
        raise RuntimeError("init_db_pool() must be called first")
    now = datetime.utcnow()
    sql = "SELECT chat_id, invite_link FROM invite_links WHERE user_id=%s AND expires_at>%s;"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (user_id, now))
                return await cur.fetchall()
    except Exception as e:
        await log_and_report(e, f"get_valid_invite_links({user_id})")
        return []

async def delete_invite_links(user_id: int) -> None:
    """
    Очищает все invite_links пользователя.
    """
    if pool is None:
        raise RuntimeError("init_db_pool() must be called first")
    sql = "DELETE FROM invite_links WHERE user_id=%s;"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (user_id,))
            await conn.commit()
        logging.info(f"[DB] delete_invite_links: {user_id}")
    except Exception as e:
        await log_and_report(e, f"delete_invite_links({user_id})")


# ------------ TRACKED CHATS CRUD ------------

async def get_all_chats() -> list[int]:
    """Возвращает все chat_id из таблицы chats для отслеживания подписок."""
    if pool is None:
        raise RuntimeError("init_db_pool() must be called before get_all_chats()")
    sql = "SELECT id FROM chats;"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        await log_and_report(e, "get_all_chats()")
        return []

