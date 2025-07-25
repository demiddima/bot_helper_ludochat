# logger.py

import logging
import sys
import httpx
import http.client
import html
import config
import aiohttp.http_exceptions
from aiohttp.http_exceptions import BadHttpMessage, BadStatusLine as AioBadStatusLine


# Фильтр для игнорирования сообщений "is not handled"
class IgnoreNotHandledUpdatesFilter(logging.Filter):
    """Игнорирует логи вида 'Update id=… is not handled.' и 'Update id=… is handled. Duration…'."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # не пропускаем, если это сообщение об обновлении – как не обработанном, так и обработанном
        ignore_subs = ["is not handled.", "is handled. Duration"]
        return not any(sub in msg for sub in ignore_subs)

# Новый фильтр для access-логов
class IgnoreStaticPathsFilter(logging.Filter):
    """Игнорирует записи access-лога для указанных URL-путей."""
    def __init__(self, ignore_paths: list[str]):
        super().__init__()
        self.ignore_paths = ignore_paths

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # пропускаем запись, если в сообщении встречается любой из путей
        return not any(path in msg for path in self.ignore_paths)


class IgnoreBadStatusLineFilter(logging.Filter):
    """Фильтр, игнорирующий ошибки BadStatusLine и сообщения с 'Invalid method encountered'."""
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if exc_type and issubclass(exc_type, (
                http.client.BadStatusLine,
                httpx.RemoteProtocolError,
                aiohttp.http_exceptions.HttpProcessingError,
                aiohttp.http_exceptions.BadHttpMessage,
                AioBadStatusLine
            )):
                return False
        msg = record.getMessage()
        if any(sub in msg for sub in ["Invalid method encountered", "BadStatusLine", "TLSV1_ALERT"]):
            return False
        return True


class TelegramHandler(logging.Handler):
    """ERROR+ логи отправляются в Telegram Bot API."""
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.token = config.BOT_TOKEN
        self.chat_id = config.ERROR_LOG_CHANNEL_ID

    def emit(self, record: logging.LogRecord) -> None:
        if not self.token or not self.chat_id:
            return
        if record.exc_info:
            etype = record.exc_info[0]
            if etype and issubclass(etype, (
                http.client.BadStatusLine,
                httpx.RemoteProtocolError,
                aiohttp.http_exceptions.HttpProcessingError
            )):
                return
        text = self.format(record)
        escaped = html.escape(text)
        max_len = 4096 - len("<pre></pre>")
        for start in range(0, len(escaped), max_len):
            segment = escaped[start:start+max_len]
            payload = f"<pre>{segment}</pre>"
            try:
                resp = httpx.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": payload, "parse_mode": "HTML"},
                    timeout=5.0
                )
                if resp.status_code != 200:
                    print(f"[Logger] Telegram API error {resp.status_code}: {resp.text}", file=sys.stderr)
            except Exception as e:
                print(f"[Logger] Failed to send log chunk to Telegram: {e}", file=sys.stderr)


def configure_logging() -> None:
    
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.INFO)

    # общий формат
    fmt = '%(asctime)s - %(levelname)s - [%(funcName)s/%(module)s] - [%(user_id)s] - %(message)s'
    formatter = logging.Formatter(fmt)

    # Консольный хендлер
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    ch.addFilter(IgnoreNotHandledUpdatesFilter())
    root.addHandler(ch)

    # Telegram handler
    th = TelegramHandler()
    th.setLevel(logging.ERROR)
    th.setFormatter(formatter)
    th.addFilter(IgnoreBadStatusLineFilter())
    th.addFilter(IgnoreNotHandledUpdatesFilter())
    root.addHandler(th)

    # Отключаем детализированные логи HTTPX, Aiogram, aiohttp
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.ERROR)

    # Добавляем фильтр для uvicorn.access — игнорируем статические запросы
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(logging.WARNING)
    static_paths = ["/favicon.ico", "/robots.txt", "/sitemap.xml", "/config.json"]
    access_logger.addFilter(IgnoreStaticPathsFilter(static_paths))
