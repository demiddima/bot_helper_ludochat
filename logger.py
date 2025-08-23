# logger.py
# Commit: убрать автозапуск configure_logging() — конфиг вызывается из main.py

import logging
import sys
import html
import http.client
import httpx
import aiohttp.http_exceptions
from aiohttp.http_exceptions import HttpProcessingError, BadHttpMessage, BadStatusLine as AioBadStatusLine
import config

class IgnoreBadStatusLineFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
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
    def filter(self, record):
        return "Update id=" not in record.getMessage()


class IgnoreStaticPathsFilter(logging.Filter):
    def __init__(self, ignore_paths):
        super().__init__()
        self.ignore_paths = ignore_paths
    def filter(self, record):
        msg = record.getMessage()
        return not any(path in msg for path in self.ignore_paths)


class CustomFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, "user_id"):
            record.user_id = "system"
        return super().format(record)


class TelegramHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.token = config.BOT_TOKEN
        self.chat_id = config.ERROR_LOG_CHANNEL_ID

    def emit(self, record):
        if not self.token or not self.chat_id:
            return
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
            seg = escaped[start:start+max_len]
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
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.INFO)

    fmt = '%(asctime)s - %(levelname)s - [%(funcName)s/%(module)s] - [%(user_id)s] - %(message)s'
    formatter = CustomFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    ch.addFilter(IgnoreUpdateFilter())
    root.addHandler(ch)

    th = TelegramHandler()
    th.setFormatter(formatter)
    th.addFilter(IgnoreBadStatusLineFilter())
    th.addFilter(IgnoreUpdateFilter())
    root.addHandler(th)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.ERROR)

    access = logging.getLogger("uvicorn.access")
    access.setLevel(logging.INFO)
    access.addFilter(IgnoreStaticPathsFilter([
        "/favicon.ico", "/robots.txt", "/sitemap.xml", "/config.json", "/.env", "/.git/"
    ]))

# ⬅️ Никакого configure_logging() тут не вызываем. Вызывается в main.py.
