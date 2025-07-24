import logging
import sys
import httpx
import http.client
import html
import config  # <-- возвращаем сюда config
import aiohttp.http_exceptions
from aiohttp.http_exceptions import BadHttpMessage, BadStatusLine as AioBadStatusLine

class IgnoreBadStatusLineFilter(logging.Filter):
    """Фильтр, игнорирующий ошибки BadStatusLine и сообщения с 'Invalid method encountered'."""
    def filter(self, record: logging.LogRecord) -> bool:
        # 1. Фильтрация по типу исключения
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if exc_type:
                # aiohttp, http.client, httpx
                if issubclass(exc_type, (
                    http.client.BadStatusLine,
                    httpx.RemoteProtocolError,
                    aiohttp.http_exceptions.HttpProcessingError,
                    aiohttp.http_exceptions.BadHttpMessage,
                    AioBadStatusLine
                )):
                    return False
        # 2. Фильтрация по содержанию текста лога
        msg = record.getMessage()
        if any(sub in msg for sub in [
            "Invalid method encountered",
            "BadStatusLine",
            "TLSV1_ALERT"
        ]):
            return False

        return True

class TelegramHandler(logging.Handler):
    """ERROR+ логи отправляются в Telegram Bot API."""
    def __init__(self):
        super().__init__(level=logging.ERROR)  # Убедимся, что только ошибки отправляются
        self.token = config.BOT_TOKEN
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
    """Настраивает:
      - INFO+ → консоль
      - ERROR+ → Telegram
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)  # Устанавливаем уровень INFO для консоли

    # Создаем формат логирования
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(funcName)s/%(module)s] - [%(user_id)s] - %(message)s')

    # console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)  # Логирование на уровне INFO для консоли
    ch.setFormatter(log_formatter)
    root.addHandler(ch)

    # telegram
    th = TelegramHandler()
    th.setFormatter(log_formatter)
    th.addFilter(IgnoreBadStatusLineFilter())  # Применяем фильтрацию ненужных HTTP-ошибок
    root.addHandler(th)
    
    # Убираем детализированные логи HTTPX и Aiogram
    logging.getLogger("httpx").setLevel(logging.WARNING)  # Логируем только ошибки для httpx
    logging.getLogger("aiogram").setLevel(logging.WARNING)  # Логируем только ошибки для aiogram
    logging.getLogger("aiohttp").setLevel(logging.ERROR)  # Установим только ERROR для aiohttp
