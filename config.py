# config.py
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


def get_env_int_choice(key: str, default: int, choices: set[int]) -> int:
    """
    Гибкое чтение числового режима из .env:
    - пробуем привести к int;
    - поддерживаем строки true/false → 1/0 для обратной совместимости;
    - если невалидно или не из допустимых значений — логируем warning и возвращаем default.
    """
    raw = os.getenv(key, None)
    if raw is None:
        logging.info(f"{key} is not set; using default {default}")
        return default

    s = str(raw).strip().lower()
    # Поддержка булевых значений в .env (историческая совместимость)
    if s in {"true", "yes", "on"}:
        val = 1
    elif s in {"false", "no", "off"}:
        val = 0
    else:
        try:
            val = int(s)
        except ValueError:
            logging.warning(f"{key} has invalid value '{raw}', falling back to {default}")
            return default

    if val not in choices:
        logging.warning(f"{key}={val} is not in allowed {sorted(choices)}; falling back to {default}")
        return default

    return val


try:
    # Настроим логирование
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Основной токен бота
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise KeyError("BOT_TOKEN is not set")

    # Канал для логирования всех ошибок
    ERROR_LOG_CHANNEL_ID = get_env_int("ERROR_LOG_CHANNEL_ID")

    # Канал для обычных уведомлений
    LOG_CHANNEL_ID = get_env_int("LOG_CHANNEL_ID")

    # ID администраторов (через ;)
    raw_admin_user = os.getenv("ID_ADMIN_USER", "")
    ID_ADMIN_USER = {int(x) for x in raw_admin_user.split(";") if x.strip().isdigit()}

    # Режимы приглашений
    INVITE_LINK_MODE = os.getenv("INVITE_LINK_MODE", "dynamic").strip()

    # Приватные назначения
    raw_dest = os.getenv("PRIVATE_DESTINATIONS", "").strip()
    if (raw_dest.startswith('"') and raw_dest.endswith('"')) or (raw_dest.startswith("'") and raw_dest.endswith("'")):
        raw_dest = raw_dest[1:-1]

    PRIVATE_DESTINATIONS = []
    if raw_dest:
        for item in raw_dest.split(";"):  # точка с запятой — разделитель
            item = item.strip()
            if not item:
                continue
            parts = item.split(",", 2)
            title = parts[0].strip()
            chat_id_str = parts[1].strip()
            description_or_check_id = parts[2].strip() if len(parts) > 2 else ""

            if chat_id_str.startswith("http"):
                chat_id = chat_id_str
                description = ""
            else:
                try:
                    chat_id = int(chat_id_str)
                    description = description_or_check_id
                except ValueError:
                    chat_id = chat_id_str
                    description = description_or_check_id

            PRIVATE_DESTINATIONS.append(
                {
                    "title": title,
                    "chat_id": chat_id,
                    "description": description,
                }
            )

    logging.warning(f"PRIVATE_DESTINATIONS: {PRIVATE_DESTINATIONS}")

    # URL API сервиса базы
    DB_API_URL = os.getenv("DB_API_URL", "http://db-api:8000")

    # Ключ API
    API_KEY_VALUE = os.getenv("API_KEY_VALUE")
    if not API_KEY_VALUE:
        raise KeyError("API_KEY_VALUE is not set")

    # Флаг/режим приветственного сообщения:
    # 0 — без приветствия, сразу основное сообщение
    # 1 — интерактивное приветствие с кнопкой подтверждения
    # 2 — приветствие БЕЗ кнопок, затем авто-подтверждение и основное сообщение
    SHOW_WELCOME = get_env_int_choice("SHOW_WELCOME", default=1, choices={0, 1, 2})

    # BOT_ID (инициализация)
    BOT_ID = None

    # ==== Настройки рассылок ====
    BROADCAST_RATE_PER_SEC = int(os.getenv("BROADCAST_RATE_PER_SEC", "29"))
    HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
    HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
    HTTP_BACKOFF_MIN = float(os.getenv("HTTP_BACKOFF_MIN", "0.5"))
    HTTP_BACKOFF_MAX = float(os.getenv("HTTP_BACKOFF_MAX", "5.0"))

except Exception as e:
    print(f"[CONFIG ERROR] {e}", file=sys.stderr)
    sys.exit(1)
