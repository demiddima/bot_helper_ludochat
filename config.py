import os
import sys

# Load environment variables from .env file
from dotenv import load_dotenv
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
    # Database configuration
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = get_env_int("DB_PORT")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_NAME = os.getenv("DB_NAME")

    # Bot and channels configuration
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    PUBLIC_CHAT_ID = get_env_int("PUBLIC_CHAT_ID")
    LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID")
    ERROR_LOG_CHANNEL_ID = get_env_int("ERROR_LOG_CHANNEL_ID")

    # Admin IDs: comma-separated list
    ADMIN_CHAT_IDS = [
        int(x) for x in os.getenv("ADMIN_CHAT_IDS", "").split(",")
        if x.strip()
    ]

    # Private destinations: list of "title:chat_id:description"
    PRIVATE_DESTINATIONS = []
    raw = os.getenv("PRIVATE_DESTINATIONS", "")
    if raw:
        for item in raw.split(","):
            parts = item.split(":", 2)
            if len(parts) != 3:
                continue
            title, chat_id, description = parts
            PRIVATE_DESTINATIONS.append({
                "title": title,
                "chat_id": int(chat_id),
                "description": description
            })
except Exception as e:
    print(f"[CONFIG ERROR] {e}", file=sys.stderr)
    sys.exit(1)
