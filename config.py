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

    LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID")
    ERROR_LOG_CHANNEL_ID = get_env_int("ERROR_LOG_CHANNEL_ID")

    # ADMIN_CHAT_IDS: semicolon-separated list of ints
    raw_admin = os.getenv("ADMIN_CHAT_IDS", "")
    ADMIN_CHAT_IDS = [int(x) for x in raw_admin.split(";") if x]

    # INVITE link mode: static or dynamic
    INVITE_LINK_MODE = os.getenv("INVITE_LINK_MODE", "dynamic").strip()

    # PRIVATE_DESTINATIONS: entries separated by semicolons, each "Title:chat_id:Description"
    raw_dest = os.getenv("PRIVATE_DESTINATIONS", "").strip()
    # Strip surrounding quotes if present
    if (raw_dest.startswith('"') and raw_dest.endswith('"')) or (raw_dest.startswith("'") and raw_dest.endswith("'")):
        raw_dest = raw_dest[1:-1]

    PRIVATE_DESTINATIONS = []
    if raw_dest:
        for item in raw_dest.split(";"):
            item = item.strip()
            if not item:
                continue
            # split title and the rest by first colon
            title, sep, rest = item.partition(":")
            if not sep:
                continue
            # split rest into chat_id and description by last colon
            idx = rest.rfind(":")
            if idx == -1:
                continue
            chat_id = rest[:idx].strip()
            description = rest[idx+1:].strip()
            # support both URL strings (static) and numeric chat IDs (dynamic)
            if chat_id.startswith("http"):
                chat_id_value = chat_id
            else:
                chat_id_value = int(chat_id)
            PRIVATE_DESTINATIONS.append({
                "title": title.strip(),
                "chat_id": chat_id_value,
                "description": description
            })

    # REST API config for DB microservice
    DB_API_URL = os.getenv("DB_API_URL", "http://db-api:8000")

    # API key for DB service access
    API_KEY_VALUE = os.getenv("API_KEY_VALUE")
    if not API_KEY_VALUE:
        raise KeyError("API_KEY_VALUE is not set")

except Exception as e:
    print(f"[CONFIG ERROR] {e}", file=sys.stderr)
    sys.exit(1)
