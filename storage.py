import logging
import aiomysql
from aiomysql import Pool
from typing import Optional
from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, BOT_TOKEN, ERROR_LOG_CHANNEL_ID
from aiogram import Bot
from utils import log_and_report

# Инициализация пула соединений и бота
pool: Optional[Pool] = None
bot = Bot(token=BOT_TOKEN)

# Словарь для хранения временных запросов на вступление
join_requests: dict[int, float] = {}

def cleanup_join_requests() -> None:
    """
    Опциональная функция очистки старых запросов.
    """
    pass

def get_bot_instance() -> Bot:
    """
    Возвращает единый экземпляр бота для отправки сообщений.
    """
    return bot

async def init_db_pool() -> None:
    global pool
    try:
        pool = await aiomysql.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            autocommit=True,
            minsize=1,
            maxsize=10,
        )
        logging.info("[DB] Пул соединений инициализирован")
        # Создание таблиц, если они не существуют
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                create_chats_sql = """
                CREATE TABLE IF NOT EXISTS chats (
                    id BIGINT PRIMARY KEY,
                    title VARCHAR(255),
                    type VARCHAR(50)
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
                await cur.execute(create_chats_sql)
                logging.info("[DB] Таблица chats создана/проверена")
                await cur.execute(create_memberships_sql)
                logging.info("[DB] Таблица user_memberships создана/проверена")
    except Exception as e:
        await log_and_report(e, "init_db_pool")

async def upsert_chat(chat_id: int, title: str, chat_type: str) -> None:
    """
    Добавляет или обновляет информацию о чате в базе.
    """
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед upsert_chat()")
    sql = """
    INSERT INTO chats (id, title, type)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE title = VALUES(title), type = VALUES(type);
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (chat_id, title, chat_type))
                logging.info(f"[DB] Chat {chat_id} upserted")
    except Exception as e:
        await log_and_report(e, f"upsert_chat({chat_id})")

async def delete_chat(chat_id: int) -> None:
    """
    Удаляет информацию о чате из базы.
    """
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед delete_chat()")
    sql = "DELETE FROM chats WHERE id = %s;"
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (chat_id,))
                logging.info(f"[DB] Chat {chat_id} deleted")
    except Exception as e:
        await log_and_report(e, f"delete_chat({chat_id})")

async def add_user_to_chat(user_id: int, chat_id: int, username: str, full_name: str) -> None:
    """
    Добавляет информацию о пользователе в чат (user_memberships).
    """
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед add_user_to_chat()")
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
                await cur.execute(sql, (user_id, chat_id, username, full_name))
                logging.info(f"[DB] User {user_id} added to chat {chat_id}")
    except Exception as e:
        await log_and_report(e, f"add_user_to_chat({user_id}, {chat_id})")

async def remove_user_from_chat(user_id: int, chat_id: int) -> None:
    """
    Удаляет информацию о пользователе из чата (user_memberships).
    """
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

async def log_and_report(error: Exception, context: str) -> None:
    """
    Логирует ошибку и отправляет отчёт в канал с ошибками.
    """
    logging.error(f"[ERROR] {context}: {error}")
    try:
        await bot.send_message(chat_id=ERROR_LOG_CHANNEL_ID, text=f"Error in {context}: {error}")
    except Exception as send_error:
        logging.error(f"[ERROR] Failed to send log message: {send_error}")
