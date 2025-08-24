# messages.py
from pathlib import Path

# Папка с HTML-шаблонами
TEXT_DIR = Path(__file__).parent / "text"

# Файлы-шаблоны
AD_FILE         = TEXT_DIR / "advertisement.html"    # баннер «Наши ресурсы» (общий)
AD_FILE_1       = TEXT_DIR / "advertisement_1.html"  # Лудочат
AD_FILE_2       = TEXT_DIR / "advertisement_2.html"  # Практичат
AD_FILE_3       = TEXT_DIR / "advertisement_3.html"  # Выручат
WELCOME_FILE    = TEXT_DIR / "welcome.html"          # приветствие при /start
ANONYMITY_FILE  = TEXT_DIR / "anonymity.html"        # секция «Анонимность»
PROJECTS_FILE   = TEXT_DIR / "projects.html"         # секция «Все проекты»

# Дефолтные тексты на случай отсутствия файлов
DEFAULT_AD_TEXT = (
    "<b>Наше сообщество:</b>\n\n"
    "<a href=\"https://t.me/joinchat/as3JmHK21sxhMGEy\">Лудочат</a> — главный чат сообщества, где лудоманы "
    "обмениваются опытом, делятся личными историями и результатами.\n"
    "<a href=\"https://t.me/viruchkaa_bot\">Выручат</a> — чат механизма и бота «Выручка»: продать аккаунт БК, "
    "заблокировать доступ к БК/казино/ЦУПИС, снять ограничения по ФЗ-115, узнать способы заработка до 25 000 ₽ "
    "и получить другие практические советы.\n"
    "<b>Практичат</b> — чат практики: профессиональные подходы и проверенные методы работы с зависимостью."
)
DEFAULT_AD_1_TEXT = "Это баннер номер 1. Информация для пользователей."
DEFAULT_AD_2_TEXT = "Это баннер номер 2. Дополнительная информация."
DEFAULT_AD_3_TEXT = "Это баннер номер 3. Дополнительная информация."
DEFAULT_WELCOME_TEXT = (
    "<b>Нажимая кнопку, вы подтверждаете, что:</b>\n\n"
    "- вы не бот\n"
    "- вам исполнилось 18 лет\n\n"
    "<b>Важно понимать:</b> чат — не медицинское сообщество и не оказывает квалифицированную помощь напрямую. "
    "Общение в чате не заменяет лечение, это лишь поддержка. Если вам тяжело, обратитесь к специалистам. "
    "Вы сами отвечаете за последствия применения информации из чата. Фильтруйте её и используйте с умом."
)

DEFAULT_ANON_TEXT = "Раздел «Анонимность» временно недоступен. Попробуйте позже."
DEFAULT_PROJ_TEXT = "Раздел «Все проекты» временно недоступен. Попробуйте позже."

def _read_file(path: Path, default: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default

def get_ad_text() -> str:
    return _read_file(AD_FILE, DEFAULT_AD_TEXT)

def get_ad_1_text() -> str:
    """Лудочат (баннер №1)."""
    return _read_file(AD_FILE_1, DEFAULT_AD_1_TEXT)

def get_ad_2_text() -> str:
    """Практичат (баннер №2)."""
    return _read_file(AD_FILE_2, DEFAULT_AD_2_TEXT)

def get_ad_3_text() -> str:
    """Выручат (баннер №3)."""
    return _read_file(AD_FILE_3, DEFAULT_AD_3_TEXT)

def get_welcome_text() -> str:
    """Приветствие при старте."""
    return _read_file(WELCOME_FILE, DEFAULT_WELCOME_TEXT)

def get_anonymity_text() -> str:
    """Секция «Анонимность»."""
    return _read_file(ANONYMITY_FILE, DEFAULT_ANON_TEXT)

def get_projects_text() -> str:
    """Секция «Все проекты»."""
    return _read_file(PROJECTS_FILE, DEFAULT_PROJ_TEXT)

# ===== Тексты для меню и экрана «Рассылки» =====

DEFAULT_SUBSCRIPTIONS_TEXT = """
<b>Управление рассылками</b>

• <b>Новости</b> — апдейты проекта, статьи, релизы, записи
• <b>Встречи</b> — анонсы онлайн встреч и созвонов (за 2-3д и 10мин)
• <b>Важные послания</b> — редкие, но критичные сообщения

<b>Текущее состояние:</b>
— Новости: {news}
— Встречи: {meetings}
— Важные послания: {important}
"""

def get_subscriptions_text(news: bool, meetings: bool, important: bool) -> str:
    """Текстовое описание состояния подписок (заглушка)."""
    return DEFAULT_SUBSCRIPTIONS_TEXT.format(
        news="Вкл" if news else "Выкл",
        meetings="Вкл" if meetings else "Выкл",
        important="Вкл" if important else "Выкл"
    )

def get_menu_title_text() -> str:
    """Заголовок меню (жирным)."""
    return "<b>Доступные разделы:</b>"
