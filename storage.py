# storage.py
import logging
import aiomysql
from aiomysql import Pool
from typing import Optional
from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

pool: Optional[Pool] = None

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
        logging.critical(f"[DB] Ошибка при создании пула: {e}")
        raise
    await init_tables()

async def init_tables() -> None:
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед init_tables()")
    create_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id BIGINT PRIMARY KEY,
        username VARCHAR(255),
        full_name VARCHAR(255),
        invite_link TEXT,
        is_verified TINYINT DEFAULT 0
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(create_sql)
                logging.info("[DB] Таблица users создана/проверена")
    except Exception as e:
        logging.error(f"[DB] Ошибка при создании таблицы users: {e}")

async def add_user(uid: int, username: str | None, full_name: str | None) -> None:
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед add_user()")
    sql = """
    INSERT INTO users (id, username, full_name, invite_link, is_verified)
    VALUES (%s, %s, %s, NULL, 0) AS newuser
    ON DUPLICATE KEY UPDATE
        username = newuser.username,
        full_name = newuser.full_name;
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (uid, username or "", full_name or ""))
                logging.info(f"[DB] Пользователь {uid} добавлен/обновлён (is_verified=0)")
    except Exception as e:
        logging.error(f"[DB] Ошибка add_user({uid}): {e}")

async def verify_user(uid: int, invite_link: str) -> None:
    if pool is None:
        raise RuntimeError("init_db_pool() должно быть вызвано перед verify_user()")
    sql = """
    UPDATE users
       SET invite_link = %s, is_verified = 1
     WHERE id = %s;
    """
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (invite_link, uid))
                logging.info(f"[DB] Пользователь {uid} отмечен как verified, invite_link сохранён")
    except Exception as e:
        logging.error(f"[DB] Ошибка verify_user({uid}): {e}")
