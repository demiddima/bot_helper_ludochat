# logger.py
import logging, httpx, html
import config

class TelegramHandler(logging.Handler):
    """ ERROR+ логи шлёт в канал из config.ERROR_LOG_CHANNEL_ID """
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.token = config.BOT_TOKEN           # ваш единственный токен
        self.chat_id = config.ERROR_LOG_CHANNEL_ID

    def emit(self, record):
        if not self.token or not self.chat_id:
            return
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

    # Telegram — ERROR+
    th = TelegramHandler()
    th.setLevel(logging.ERROR)
    th.setFormatter(fmt)
    root.addHandler(th)

# запускаем при импорте
configure_logging()
