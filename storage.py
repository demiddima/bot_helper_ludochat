import logging
import aiomysql
from aiomysql import Pool
from typing import Optional
from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
from utils import log_and_report
from aiogram import Bot

# Assuming ERROR_LOG_CHANNEL_ID is defined in config
from config import ERROR_LOG_CHANNEL_ID, BOT_TOKEN

pool: Optional[Pool] = None
bot = Bot(token=BOT_TOKEN)

async def init_db_pool() -> None:
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
            autocommit=True,
            minsize=1,
            maxsize=5,
        )
        logging.info(f"[DB] Пул подключений к MySQL создан: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    except Exception as e:
        await log_and_report(e, "init_db_pool")
        raise
    try:
        await init_tables()
    except Exception as e:
        await log_and_report(e, "init_tables")
        raise

async def init_tables() -> None:
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед init_tables()")

    create_chats_sql = """
    CREATE TABLE IF NOT EXISTS chats (
        id BIGINT PRIMARY KEY,
        title VARCHAR(256) NOT NULL,
        type ENUM('public_channel','supergroup','group','private_channel') NOT NULL,
        added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    """

    create_memberships_sql = """
    CREATE TABLE IF NOT EXISTS user_memberships (
        user_id BIGINT NOT NULL,
        chat_id BIGINT NOT NULL,
        joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, chat_id),
        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(create_chats_sql)
            logging.info("[DB] Таблица chats создана/проверена")
            await cur.execute(create_memberships_sql)
            logging.info("[DB] Таблица user_memberships создана/проверена")

async def upsert_chat(chat_id: int, title: str, type_: str) -> None:
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед upsert_chat()")
    sql = """
    INSERT INTO chats (id, title, type)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE title = %s;
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (chat_id, title, type_, title))
                logging.info(f"[DB] Чат {chat_id} ({title}) сохранён/обновлён")
    except Exception as e:
        await log_and_report(e, f"upsert_chat({chat_id})")

async def delete_chat(chat_id: int) -> None:
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед delete_chat()")
    sql = "DELETE FROM chats WHERE id = %s;"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (chat_id,))
                logging.info(f"[DB] Чат {chat_id} удалён из списка")
    except Exception as e:
        await log_and_report(e, f"delete_chat({chat_id})")

async def add_user_to_chat(user_id: int, chat_id: int) -> None:
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед add_user_to_chat()")
    sql = """
    INSERT INTO user_memberships (user_id, chat_id)
    VALUES (%s, %s)
    ON DUPLICATE KEY UPDATE joined_at = CURRENT_TIMESTAMP;
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (user_id, chat_id))
                logging.info(f"[DB] Пользователь {user_id} добавлен в чат {chat_id}")
    except Exception as e:
        await log_and_report(e, f"add_user_to_chat({user_id}, {chat_id})")

async def remove_user_from_chat(user_id: int, chat_id: int) -> None:
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед remove_user_from_chat()")
    sql = "DELETE FROM user_memberships WHERE user_id = %s AND chat_id = %s;"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (user_id, chat_id))
                logging.info(f"[DB] Пользователь {user_id} удалён из чата {chat_id}")
    except Exception as e:
        await log_and_report(e, f"remove_user_from_chat({user_id}, {chat_id})")
