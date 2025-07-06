# config.py

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
    # Основной токен бота (используется и для логирования ошибок)
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise KeyError("BOT_TOKEN is not set")

    # Уровень логирования: в консоль INFO+, в Telegram-канал ERROR+
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Канал для логирования всех ошибок
    ERROR_LOG_CHANNEL_ID = get_env_int("ERROR_LOG_CHANNEL_ID")

    # Канал для обычных уведомлений (если используется)
    LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID")

    # Списки админов для команд администрирования чатов
    raw_admin = os.getenv("ADMIN_CHAT_IDS", "")
    ADMIN_CHAT_IDS = [int(x) for x in raw_admin.split(";") if x]

    # ID пользователей, которым разрешено менять MORE_INFO
    raw_admin_user = os.getenv("ID_ADMIN_USER", "")
    # Приводим к множеству целых для быстрого in-проверки
    ID_ADMIN_USER = {int(x) for x in raw_admin_user.split(";") if x}

    # Режимы приглашений
    INVITE_LINK_MODE = os.getenv("INVITE_LINK_MODE", "dynamic").strip()

    # Приватные назначения
    raw_dest = os.getenv("PRIVATE_DESTINATIONS", "").strip()
    if (raw_dest.startswith('"') and raw_dest.endswith('"')) or (raw_dest.startswith("'") and raw_dest.endswith("'")):
        raw_dest = raw_dest[1:-1]

    PRIVATE_DESTINATIONS = []
    if raw_dest:
        for item in raw_dest.split(";"):
            item = item.strip()
            if not item:
                continue
            title, sep, rest = item.partition(":")
            if not sep:
                continue

            parts = rest.rsplit(":", 2)
            if len(parts) == 3:
                chat_id_str, description, check_id_str = [p.strip() for p in parts]
            elif len(parts) == 2:
                chat_id_str, description = [p.strip() for p in parts]
                check_id_str = None
            else:
                chat_id_str = parts[0].strip()
                description = ""
                check_id_str = None

            # Преобразуем chat_id
            if chat_id_str.startswith("http"):
                chat_id = chat_id_str
            else:
                chat_id = int(chat_id_str)

            # Необязательный check_id
            if check_id_str:
                try:
                    check_id = int(check_id_str)
                except ValueError:
                    check_id = None
            else:
                check_id = None

            dest = {
                "title": title.strip(),
                "chat_id": chat_id,
                "description": description
            }
            if check_id is not None:
                dest["check_id"] = check_id

            PRIVATE_DESTINATIONS.append(dest)

    # URL базы данных (сервис)
    DB_API_URL = os.getenv("DB_API_URL", "http://db-api:8000")

    # Ключ API для других микросервисов
    API_KEY_VALUE = os.getenv("API_KEY_VALUE")
    if not API_KEY_VALUE:
        raise KeyError("API_KEY_VALUE is not set")

except Exception as e:
    print(f"[CONFIG ERROR] {e}", file=sys.stderr)
    sys.exit(1)
