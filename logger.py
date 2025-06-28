import logging
import httpx
import html
import config
from aiohttp.http_exceptions import BadStatusLine, BadHttpMessage

class TelegramHandler(logging.Handler):
    """ ERROR+ логи шлёт в канал из config.ERROR_LOG_CHANNEL_ID """
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.token = config.BOT_TOKEN           # ваш единственный токен
        self.chat_id = config.ERROR_LOG_CHANNEL_ID

        # Список типов исключений или фрагментов сообщений, которые нужно игнорировать
        self._ignore_exc_types = (BadStatusLine, BadHttpMessage)
        self._ignore_message_substrings = (
            "Invalid method encountered",
            "Pause on PRI/Upgrade",
        )

    def emit(self, record):
        # Фильтруем по типу исключения
        if record.exc_info and isinstance(record.exc_info[1], self._ignore_exc_types):
            return

        # Фильтруем по содержимому текста
        msg_text = record.getMessage()
        for substr in self._ignore_message_substrings:
            if substr in msg_text:
                return

        # Если токен или чат не заданы — ничего не делаем
        if not self.token or not self.chat_id:
            return

        # Формируем и отправляем сообщение
        msg = self.format(record)
        payload = "<pre>" + html.escape(msg) + "</pre>"
        try:
            resp = httpx.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": payload, "parse_mode": "HTML"},
                timeout=5.0
            )
            if resp.status_code != 200:
                print(f"[Logger] Telegram API error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Logger] Failed to send log to Telegram: {e}")

def configure_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # консоль — INFO+
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Telegram — ERROR+, с фильтрацией
    th = TelegramHandler()
    th.setLevel(logging.ERROR)
    th.setFormatter(fmt)
    root.addHandler(th)

# запускаем при импорте
configure_logging()
