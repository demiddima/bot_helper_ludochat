import asyncio
import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters.command import Command

router = Router()

# Responses for slash commands with HTML formatting
RESPONSES = {
    "sell_account": {
        "text": "Чтобы продать аккаунт БК, используйте платформу по <a href=\"https://example.com/sell_account\">ссылке</a>.",
        "autodelete": True  # delete both question and answer after 120 seconds
    },
    "quit_gambling": {
        "text": "Чтобы начать путь к выздоровлению, присоединяйтесь к <a href=\"https://t.me/ludoochat_support\">каналу поддержки</a>.",
        "autodelete": False  # keep messages
    }
}

@router.message(Command(commands=["sell_account", "quit_gambling"]), F.reply_to_message)
async def handle_slash_command(message: Message):
    """
    Обрабатывает команды /sell_account и /quit_gambling, когда использованы в ответ на сообщение.
    Ведет удаление командного сообщения, отправку ответа и опциональное автoудаление.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    command_name = message.text.lstrip("/").split("@")[0].lower()

    if command_name not in RESPONSES:
        logging.info(f"[UNKNOWN] Команда {command_name} не найдена.")
        return

    # Only admins and creators allowed
    member = await message.bot.get_chat_member(chat_id, user_id)
    if member.status not in ("administrator", "creator"):
        logging.info(f"[IGNORED] {message.from_user.full_name} ({member.status}) попытался использовать {message.text}.")
        return

    replied_msg = message.reply_to_message

    try:
        await message.delete()
        logging.info(f"[DELETE CMD] Команда /{command_name} удалена.")
    except Exception as e:
        logging.warning(f"[FAIL DELETE CMD] Не удалось удалить команду: {e}")

    tpl = RESPONSES[command_name]
    final_text = tpl["text"]
    autodelete = tpl["autodelete"]

    response_message = None

    try:
        response_message = await message.bot.send_message(
            chat_id,
            final_text,
            reply_to_message_id=replied_msg.message_id,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logging.info(f"[SENT CHAT] Ответ на команду /{command_name} отправлен.")
    except Exception as e:
        logging.warning(f"[FAIL SEND CHAT] Не удалось отправить ответ в чат: {e}")
        return

    if autodelete:
        question_id = replied_msg.message_id
        answer_id = response_message.message_id

        async def delete_later():
            await asyncio.sleep(120)
            try:
                await message.bot.delete_message(chat_id, question_id)
                logging.info(f"[DELETE Q] Удалён вопрос (message_id={question_id}).")
            except Exception:
                pass
            try:
                await message.bot.delete_message(chat_id, answer_id)
                logging.info(f"[DELETE A] Удалён ответ (message_id={answer_id}).")
            except Exception:
                pass

        asyncio.create_task(delete_later())
