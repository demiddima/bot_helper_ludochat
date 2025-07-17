import logging
import sys
import httpx
import http.client
import html
import config  # <-- возвращаем сюда config
import aiohttp.http_exceptions
from aiohttp.http_exceptions import BadHttpMessage, BadStatusLine as AioBadStatusLine

class IgnoreBadStatusLineFilter(logging.Filter):
    """Фильтр ненужных HTTP-ошибок."""
    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if exc:
            if isinstance(exc, http.client.BadStatusLine):
                return False
            if isinstance(exc, httpx.RemoteProtocolError):
                return False
            if isinstance(exc, aiohttp.http_exceptions.HttpProcessingError):
                return False
            if isinstance(exc, (BadHttpMessage, AioBadStatusLine)):
                return False
            if "Invalid method encountered" in str(exc):
                return False
        return True

class TelegramHandler(logging.Handler):
    """ERROR+ логи отправляются в Telegram Bot API."""
    def __init__(self):
        super().__init__(level=logging.ERROR)  # Убедимся, что только ошибки отправляются
        self.token   = config.BOT_TOKEN
        self.chat_id = config.ERROR_LOG_CHANNEL_ID

    def emit(self, record: logging.LogRecord) -> None:
        if not self.token or not self.chat_id:
            return

        # фильтр «пустых» HTTP-исключений
        if record.exc_info:
            etype = record.exc_info[0]
            if etype and issubclass(etype, (
                http.client.BadStatusLine,
                httpx.RemoteProtocolError,
                aiohttp.http_exceptions.HttpProcessingError
            )):  # Если ошибка из HTTP-запросов, игнорируем
                return

        text    = self.format(record)
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
    """Настраивает:
      - WARNING+ → консоль
      - ERROR+ → Telegram
    """
    root = logging.getLogger()
    root.setLevel(logging.WARNING)  # Устанавливаем уровень WARNING для консоли

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)  # Логирование на уровне WARNING для консоли
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # telegram
    th = TelegramHandler()
    th.setFormatter(fmt)
    th.addFilter(IgnoreBadStatusLineFilter())  # Применяем фильтрацию ненужных HTTP-ошибок
    root.addHandler(th)

    # suppress aiohttp.server noisy BadStatusLine
    server_logger = logging.getLogger("aiohttp.server")
    server_logger.setLevel(logging.ERROR)  # Устанавливаем уровень ERROR для серверных логов
    server_logger.addFilter(IgnoreBadStatusLineFilter())

    # Уменьшаем уровень логирования для httpx
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.WARNING)  # Логируем только ошибки для httpx
