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
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    PUBLIC_CHAT_ID = get_env_int("PUBLIC_CHAT_ID")
    LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID")
    ERROR_LOG_CHANNEL_ID = get_env_int("ERROR_LOG_CHANNEL_ID")

    ADMIN_CHAT_IDS_RAW = os.getenv("ADMIN_CHAT_IDS", "")
    if not ADMIN_CHAT_IDS_RAW:
        raise KeyError("ADMIN_CHAT_IDS is not set or is empty")
    # Parse comma-separated list of admin IDs into a Python list of ints
ADMIN_CHAT_IDS = [
    int(x) for x in os.getenv("ADMIN_CHAT_IDS", "").split(",")
    if x.strip()
]


    DB_HOST = os.environ["DB_HOST"]
    DB_PORT = get_env_int("DB_PORT")
    DB_USER = os.environ["DB_USER"]
    DB_PASSWORD = os.environ["DB_PASSWORD"]
    DB_NAME = os.environ["DB_NAME"]

    raw_private = os.getenv("PRIVATE_DESTINATIONS", "")
    if raw_private:
        PRIVATE_DESTINATIONS = []
        for item in raw_private.split(";"):
            if not item:
                continue
            parts = item.split(":")
            if len(parts) != 3:
                continue
            title, chat_id, description = parts
            PRIVATE_DESTINATIONS.append({
                "title": title,
                "chat_id": int(chat_id),
                "description": description
            })
    else:
        PRIVATE_DESTINATIONS = []

except Exception as e:
    print(f"[CONFIG ERROR] {e}", file=sys.stderr)
    sys.exit(1)
