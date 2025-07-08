import logging
import sys
import httpx
import http.client
import html
import config
import aiohttp.http_exceptions
from aiohttp.http_exceptions import BadHttpMessage, BadStatusLine as AioBadStatusLine

class IgnoreBadStatusLineFilter(logging.Filter):
    """
    Игнорирует:
    - ошибки TLS handshake на HTTP-порте (BadStatusLine из http.client)
    - ошибки RemoteProtocolError из httpx
    - любые HTTP-просчеты aiohttp (HttpProcessingError, BadHttpMessage, BadStatusLine)
    - любые исключения, где текст содержит 'Invalid method encountered'
    """
    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if exc:
            # http.client.BadStatusLine
            if isinstance(exc, http.client.BadStatusLine):
                return False
            # httpx.RemoteProtocolError
            if isinstance(exc, httpx.RemoteProtocolError):
                return False
            # aiohttp HTTP errors
            if isinstance(exc, aiohttp.http_exceptions.HttpProcessingError):
                return False
            # BadHttpMessage и BadStatusLine в aiohttp
            if isinstance(exc, (BadHttpMessage, AioBadStatusLine)):
                return False
            # По тексту
            if "Invalid method encountered" in str(exc):
                return False
        return True

class TelegramHandler(logging.Handler):
    """
    Отправляет логи уровня ERROR и выше в Telegram через Bot API.
    """
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.token = config.BOT_TOKEN
        self.chat_id = config.ERROR_LOG_CHANNEL_ID

    def emit(self, record: logging.LogRecord) -> None:
        if not self.token or not self.chat_id:
            return

        # Пропускаем нежелательные исключения
        if record.exc_info:
            exc_type = record.exc_info[0]
            if exc_type and issubclass(exc_type, (
                http.client.BadStatusLine,
                httpx.RemoteProtocolError,
                aiohttp.http_exceptions.HttpProcessingError
            )):
                return

        text = self.format(record)
        payload = "<pre>" + html.escape(text) + "</pre>"

        try:
            resp = httpx.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": payload, "parse_mode": "HTML"},
                timeout=5.0
            )
            if resp.status_code != 200:
                print(f"[Logger] Telegram API error {resp.status_code}: {resp.text}", file=sys.stderr)
        except Exception as e:
            # Чтобы не зациклить логирование ошибок внутри логгера
            print(f"[Logger] Failed to send log to Telegram: {e}", file=sys.stderr)

def configure_logging() -> None:
    # Всегда выводим INFO+ в консоль
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Console — INFO+
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Telegram — ERROR+, с фильтром IgnoreBadStatusLineFilter
    th = TelegramHandler()
    th.setFormatter(fmt)
    th.addFilter(IgnoreBadStatusLineFilter())
    root.addHandler(th)

    # Подавить BadStatusLine-ошибки от aiohttp.server в консоли
    server_logger = logging.getLogger("aiohttp.server")
    server_logger.setLevel(logging.WARNING)
    server_logger.addFilter(IgnoreBadStatusLineFilter())

# Инициализируем логирование при импорте
configure_logging()
