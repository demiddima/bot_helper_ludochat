# config_example.py
# ----------
# Пример конфигурации для MySQL.
# Скопируйте этот файл в config.py и заполните реальные значения в окружении.

import os

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PUBLIC_CHAT_ID = int(os.getenv("PUBLIC_CHAT_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
ERROR_LOG_CHANNEL_ID = int(os.getenv("ERROR_LOG_CHANNEL_ID", "0"))

# MySQL настройки
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_NAME = os.getenv("DB_NAME", "database")

# Приватные чаты для Invite
PRIVATE_DESTINATIONS = [
    {
        "title": "Лудочат",
        "chat_id": int(os.getenv("LUDOCHAT_ID", "0")),
        "description": "Основной чат поддержки."
    }
]

# Админские команды в чатах
raw_admins = os.getenv("ADMIN_CHAT_IDS", "")
if raw_admins:
    ADMIN_CHAT_IDS = [int(x) for x in raw_admins.split(",") if x.strip()]
else:
    ADMIN_CHAT_IDS = []
