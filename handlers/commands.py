import asyncio
import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters.command import Command
from aiogram.enums import ParseMode

router = Router()

RESPONSES = {
    "sell_account": {
        "text": "Приветствуем, {username}. Ответы на все ваши вопросы можете найти здесь: [ссылка](https://example.com).",
        "private": False,
        "autodelete": True
    },
    "quit_gambling": {
        "text": "Всего существует 3 способа ...",
        "private": False,
        "autodelete": False
    }
}

@router.message(Command(commands=["sell_account", "quit_gambling"]), F.reply_to_message)
async def handle_slash_command(message: Message):
    """
    Обрабатывает команды /sell_account и /quit_gambling, но только если админ/creator
    и если команда отправлена в ответ на сообщение.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    member = await message.bot.get_chat_member(chat_id, user_id)
    if member.status not in ("administrator", "creator"):
        logging.info(f"[IGNORED] {message.from_user.full_name} ({member.status}) попытался использовать {message.text}.")
        return

    command_name = message.text.lstrip("/").split("@")[0]

    if command_name not in RESPONSES:
        logging.info(f"[UNKNOWN] Команда {command_name} не найдена в RESPONSES.")
        return

    replied_msg = message.reply_to_message
    target_user = replied_msg.from_user
    username_to_insert = f"@{target_user.username}" if target_user.username else target_user.full_name

    try:
        await message.delete()
        logging.info(f"[DELETE CMD] Команда /{command_name} удалена.")
    except Exception as e:
        logging.warning(f"[FAIL DELETE CMD] Не удалось удалить команду: {e}")

    tpl = RESPONSES[command_name]
    text_template = tpl["text"]
    send_private = tpl["private"]
    autodelete = tpl["autodelete"]

    final_text = text_template.replace("{username}", username_to_insert)

    response_message = None

    if send_private:
        try:
            await message.bot.send_message(target_user.id, final_text, parse_mode=ParseMode.MARKDOWN)
            logging.info(f"[SENT PRIVATE] Ответ отправлен в личку {username_to_insert}.")
        except Exception as e:
            logging.warning(f"[FAIL SEND PRIVATE] Не удалось отправить ответ в личку: {e}")
    else:
        try:
            response_message = await message.bot.send_message(
                chat_id,
                final_text,
                reply_to_message_id=replied_msg.message_id,
                parse_mode=ParseMode.MARKDOWN
            )
            logging.info(f"[SENT CHAT] Ответ в чат (message_id={response_message.message_id}).")
        except Exception as e:
            logging.warning(f"[FAIL SEND CHAT] Не удалось отправить ответ в чат: {e}")
            return

    if autodelete:
        question_id = replied_msg.message_id
        answer_id = response_message.message_id if response_message else None

        async def delete_later():
            await asyncio.sleep(120)
            try:
                await message.bot.delete_message(chat_id, question_id)
                logging.info(f"[DELETE Q] Удалён вопрос (message_id={question_id}).")
            except Exception:
                pass
            if answer_id:
                try:
                    await message.bot.delete_message(chat_id, answer_id)
                    logging.info(f"[DELETE A] Удалён ответ (message_id={answer_id}).")
                except Exception:
                    pass

        asyncio.create_task(delete_later())
