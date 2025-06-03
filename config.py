import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_env_int(key):
    val = os.getenv(key)
    if val is None:
        raise KeyError(f"Environment variable {key} is not set")
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"Environment variable {key} must be an integer, got: {val}")

try:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise KeyError("BOT_TOKEN is not set")

    PUBLIC_CHAT_ID = get_env_int("PUBLIC_CHAT_ID")
    LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID")
    ERROR_LOG_CHANNEL_ID = get_env_int("ERROR_LOG_CHANNEL_ID")

    # ADMIN_CHAT_IDS: allow comma or semicolon separated list of ints
    import re
    raw_admin = os.getenv("ADMIN_CHAT_IDS", "")
    ADMIN_CHAT_IDS = [int(x) for x in re.split(r"[,;]", raw_admin) if x.strip()]

    # PRIVATE_DESTINATIONS: "Title:id:Description", separated by comma or semicolon
    raw_dest = os.getenv("PRIVATE_DESTINATIONS", "")
    PRIVATE_DESTINATIONS = []
    for item in re.split(r"[,;]", raw_dest):
        if item.strip():
            parts = item.split(":", 2)
            if len(parts) == 3:
                title, chat_id, description = parts
                PRIVATE_DESTINATIONS.append({
                    "title": title,
                    "chat_id": int(chat_id),
                    "description": description
                })

    # Database configuration
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = get_env_int("DB_PORT")
    DB_USER = os.getenv("DB_USER")
    if not DB_USER:
        raise KeyError("DB_USER is not set")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    if not DB_PASSWORD:
        raise KeyError("DB_PASSWORD is not set")
    DB_NAME = os.getenv("DB_NAME")
    if not DB_NAME:
        raise KeyError("DB_NAME is not set")

except Exception as e:
    print(f"[CONFIG ERROR] {e}", file=sys.stderr)
    sys.exit(1)
