# logger.py
# Commit: убрать автозапуск configure_logging() — конфиг вызывается из main.py

import logging
import sys
import re
import html
import http.client
import httpx
import aiohttp.http_exceptions
from aiohttp.http_exceptions import HttpProcessingError, BadHttpMessage, BadStatusLine as AioBadStatusLine
import config


class IgnoreBadStatusLineFilter(logging.Filter):
    """Срезает шум от кривых HTTP-клиентов/сканеров и прочего сетевого мусора."""
    def filter(self, record: logging.LogRecord) -> bool:
        # Игнорируем известные сетевые исключения
        if record.exc_info:
            exc_type = record.exc_info[0]
            if exc_type and issubclass(exc_type, (
                http.client.BadStatusLine,
                httpx.RemoteProtocolError,
                HttpProcessingError,
                BadHttpMessage,
                AioBadStatusLine
            )):
                return False

        # И известные сигнатуры мусора в сообщениях
        msg = record.getMessage()
        if any(sub in msg for sub in (
            "Invalid method encountered",
            "TLSV1_ALERT",
            "BadStatusLine",
            "b'\\x16\\x03\\x01'",
            "b'\\x05\\x01'",
            "b'\\x04\\x01'",
            "b'\\x16\\x03\\x01\\x02'",
            "b'\\x16\\x03\\x01\\x01\\x17\\x01",
            "b'OPTIONS sip",
            "aiohttp.http_exceptions.BadHttpMessage",
            "Pause on PRI/Upgrade",
            "Update id=",
            "b'MGLNDD"
        )):
            return False
        return True


class IgnoreUpdateFilter(logging.Filter):
    """Убирает мусорные логи с Update id=..."""
    def filter(self, record: logging.LogRecord) -> bool:
        return "Update id=" not in record.getMessage()


class IgnoreStaticPathsFilter(logging.Filter):
    """Фильтрует обращения к статике в access-логах веб-сервера."""
    def __init__(self, ignore_paths):
        super().__init__()
        self.ignore_paths = ignore_paths

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in self.ignore_paths)


class IgnoreHttpNoiseFilter(logging.Filter):
    """
    Делает INFO «логическим»:
    - прячет технические HTTP-запросы/ответы,
    - промежуточные статусы ChatMemberStatus.*,
    - дампы кнопок,
    - периодические бессодержательные пуллы /broadcasts.
    При DEBUG всё видно.
    """
    re_http_req = re.compile(r'^HTTP запрос → ')
    re_http_resp = re.compile(r'^HTTP ответ ← ')
    re_status = re.compile(r"status='ChatMemberStatus\.")
    re_buttons = re.compile(r'\bbuttons:\s*\[\{')
    re_broadcasts = re.compile(r'/broadcasts\?limit=')

    def filter(self, record: logging.LogRecord) -> bool:
        # Пропускаем всё, кроме уровня INFO — WARNING/ERROR/DEBUG не режем
        if record.levelno != logging.INFO:
            return True

        # Явные технические логгеры/функции
        if record.funcName in ('_log_request', '_log_response'):
            return False

        msg = record.getMessage()

        # HTTP трафик
        if self.re_http_req.search(msg) or self.re_http_resp.search(msg):
            return False

        # Промежуточные статусы
        if self.re_status.search(msg):
            return False

        # Дампы клавиатур/кнопок
        if self.re_buttons.search(msg):
            return False

        # Пустые периодические пуллы рассылок (нам важен результат, не факт запроса)
        if self.re_broadcasts.search(msg) and 'total=0' in msg:
            return False

        return True


class CustomFormatter(logging.Formatter):
    """Гарантирует наличие поля user_id в форматтере."""
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "user_id"):
            record.user_id = "system"
        return super().format(record)


class TelegramHandler(logging.Handler):
    """Отправка ERROR в телеграм-канал (без сетевого шума)."""
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.token = config.BOT_TOKEN
        self.chat_id = config.ERROR_LOG_CHANNEL_ID

    def emit(self, record: logging.LogRecord) -> None:
        if not self.token or not self.chat_id:
            return

        # Не шлём известный сетевой мусор
        if record.exc_info:
            etype = record.exc_info[0]
            if etype and issubclass(etype, (
                http.client.BadStatusLine,
                httpx.RemoteProtocolError,
                HttpProcessingError
            )):
                return

        text = self.format(record)
        escaped = html.escape(text)
        max_len = 4096 - len("<pre></pre>")

        for start in range(0, len(escaped), max_len):
            seg = escaped[start:start + max_len]
            payload = f"<pre>{seg}</pre>"
            try:
                resp = httpx.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": payload, "parse_mode": "HTML"},
                    timeout=5.0
                )
                if resp.status_code != 200:
                    print(f"[Logger] Telegram API error {resp.status_code}: {resp.text}", file=sys.stderr)
            except Exception as e:
                print(f"[Logger] Failed to send log to Telegram: {e}", file=sys.stderr)


def configure_logging():
    """
    Централизованная настройка логирования:
    - INFO показывает только «логические» события,
    - DEBUG включает полный технический след,
    - ERROR уходит в Telegram (за вычетом сетевого мусора).
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.INFO)

    fmt = '%(asctime)s - %(levelname)s - [%(funcName)s/%(module)s] - [%(user_id)s] - %(message)s'
    formatter = CustomFormatter(fmt)

    # Консоль: логический INFO
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    ch.addFilter(IgnoreUpdateFilter())
    ch.addFilter(IgnoreHttpNoiseFilter())       # ← прячем технику на INFO
    root.addHandler(ch)

    # Telegram: только ERROR (без сетевого мусора)
    th = TelegramHandler()
    th.setFormatter(formatter)
    th.addFilter(IgnoreBadStatusLineFilter())
    th.addFilter(IgnoreUpdateFilter())
    root.addHandler(th)

    # Урезаем болтливость библиотек
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.ERROR)

    # access-логи веб-сервера: фильтруем статик запросы
    access = logging.getLogger("uvicorn.access")
    access.setLevel(logging.INFO)
    access.addFilter(IgnoreStaticPathsFilter([
        "/favicon.ico", "/robots.txt", "/sitemap.xml", "/config.json", "/.env", "/.git/"
    ]))

# ⬅️ Никакого configure_logging() тут не вызываем. Вызывается в main.py.
