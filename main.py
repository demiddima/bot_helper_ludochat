# main.py
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from config import BOT_TOKEN, ADMIN_CHAT_IDS
from storage import init_db_pool
from handlers.join import router as join_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

async def main():
    await init_db_pool()
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
    dp = Dispatcher()
    dp.include_router(join_router)
    for chat_id in ADMIN_CHAT_IDS:
        try:
            logging.info(f"⚙️ Команды для админов чата {chat_id} установлены.")
        except Exception as e:
            logging.warning(f"[COMMANDS] Не удалось установить команды для {chat_id}: {e}")
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Start polling")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())