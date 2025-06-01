# config.py
import os

try:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    PUBLIC_CHAT_ID = int(os.environ["PUBLIC_CHAT_ID"])
    LOG_CHANNEL_ID = int(os.environ["LOG_CHANNEL_ID"])
    ERROR_LOG_CHANNEL_ID = int(os.environ["ERROR_LOG_CHANNEL_ID"])

    raw_private = os.getenv("PRIVATE_DESTINATIONS", "")
    if raw_private:
        PRIVATE_DESTINATIONS = []
        for item in raw_private.split(";"):
            if not item:
                continue
            parts = item.split(":")
            title, chat_id_str, desc = parts[0], parts[1], ":".join(parts[2:])
            PRIVATE_DESTINATIONS.append({
                "title": title,
                "chat_id": int(chat_id_str),
                "description": desc
            })
    else:
        raise KeyError("NO_PRIVATES")

    raw_admins = os.getenv("ADMIN_CHAT_IDS", "")
    if raw_admins:
        ADMIN_CHAT_IDS = [int(x) for x in raw_admins.split(",") if x.strip()]
    else:
        raise KeyError("NO_ADMINS")

    DB_HOST = os.environ["DB_HOST"]
    DB_PORT = int(os.environ.get("DB_PORT", "3306"))
    DB_USER = os.environ["DB_USER"]
    DB_PASSWORD = os.environ["DB_PASSWORD"]
    DB_NAME = os.environ["DB_NAME"]

except KeyError:
    from config_old import (
        BOT_TOKEN,
        PUBLIC_CHAT_ID,
        LOG_CHANNEL_ID,
        ERROR_LOG_CHANNEL_ID,
        PRIVATE_DESTINATIONS,
        ADMIN_CHAT_IDS,
        DB_HOST,
        DB_PORT,
        DB_USER,
        DB_PASSWORD,
        DB_NAME,
    )
    