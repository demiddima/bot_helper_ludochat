import os
import sys
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
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    PUBLIC_CHAT_ID = get_env_int("PUBLIC_CHAT_ID")
    LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID")
    ERROR_LOG_CHANNEL_ID = get_env_int("ERROR_LOG_CHANNEL_ID")

    # Parse ADMIN_CHAT_IDS: allow comma or semicolon
    import re
    raw_admins = os.getenv("ADMIN_CHAT_IDS", "")
    ADMIN_CHAT_IDS = [int(x) for x in re.split(r"[,;]", raw_admins) if x.strip()]

    # Parse PRIVATE_DESTINATIONS: list of "Title:id:Description"
    PRIVATE_DESTINATIONS = []
    raw_dest = os.getenv("PRIVATE_DESTINATIONS", "")
    if raw_dest:
        for item in raw_dest.split(","):
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
