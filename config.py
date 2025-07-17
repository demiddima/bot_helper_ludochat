import os
import sys
from dotenv import load_dotenv
import logging

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
    ID_ADMIN_USER = {int(x) for x in raw_admin_user.split(";") if x}

    # Режимы приглашений
    INVITE_LINK_MODE = os.getenv("INVITE_LINK_MODE", "dynamic").strip()

    # Приватные назначения
    raw_dest = os.getenv("PRIVATE_DESTINATIONS", "").strip()
    if (raw_dest.startswith('"') and raw_dest.endswith('"')) or (raw_dest.startswith("'") and raw_dest.endswith("'")):
        raw_dest = raw_dest[1:-1]

    PRIVATE_DESTINATIONS = []
    if raw_dest:
        for item in raw_dest.split(";"):  # Используем точку с запятой для разделения
            item = item.strip()
            if not item:
                continue
            parts = item.split(",", 2)  # Делим по запятой на 3 части

            # Первая часть - это title
            title = parts[0].strip()

            # Вторая часть - это chat_id или URL
            chat_id_str = parts[1].strip()

            # Третья часть - это описание или check_id
            description_or_check_id = parts[2].strip() if len(parts) > 2 else ""

            # Если chat_id это URL, то не пытаемся преобразовывать его в число
            if chat_id_str.startswith("http"):
                chat_id = chat_id_str
                description = ""
            else:
                try:
                    chat_id = int(chat_id_str)
                    description = description_or_check_id
                except ValueError:
                    chat_id = chat_id_str  # В случае ошибки сохраняем как строку
                    description = description_or_check_id

            # Формируем запись для PRIVATE_DESTINATIONS
            dest = {
                "title": title.strip(),
                "chat_id": chat_id,
                "description": description
            }

            PRIVATE_DESTINATIONS.append(dest)

    # Настроим логирование: поменяли на WARNING, чтобы избежать лишних логов
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Логируем значение PRIVATE_DESTINATIONS для проверки только при уровне ERROR или WARNING
    logging.warning(f"PRIVATE_DESTINATIONS: {PRIVATE_DESTINATIONS}")

    # URL базы данных (сервис)
    DB_API_URL = os.getenv("DB_API_URL", "http://db-api:8000")

    # Ключ API для других микросервисов
    API_KEY_VALUE = os.getenv("API_KEY_VALUE")
    if not API_KEY_VALUE:
        raise KeyError("API_KEY_VALUE is not set")

    # Инициализация BOT_ID
    BOT_ID = None  # Инициализация переменной BOT_ID

except Exception as e:
    print(f"[CONFIG ERROR] {e}", file=sys.stderr)
    sys.exit(1)
