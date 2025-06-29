import logging
import sys
import httpx
import html
import config

class IgnoreBadStatusLineFilter(logging.Filter):
    """
    Игнорирует ошибки BadStatusLine (TLS handshake на HTTP-порте)
    и сообщения с текстом 'Invalid method encountered'.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if exc and exc.__class__.__name__ == "BadStatusLine":
            return False
        msg = record.getMessage()
        if "Invalid method encountered" in msg:
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

    # Telegram — ERROR+
    th = TelegramHandler()
    th.setFormatter(fmt)
    th.addFilter(IgnoreBadStatusLineFilter())
    root.addHandler(th)

# Инициализируем логирование при импорте
configure_logging()
