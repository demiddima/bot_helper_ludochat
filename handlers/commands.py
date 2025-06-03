import asyncio
import logging
import json
import os

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters.command import Command
from aiogram.enums import ParseMode

router = Router()

# Load command responses from commands.json
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # project root
commands_file = os.path.join(BASE_DIR, 'commands.json')
try:
    with open(commands_file, 'r', encoding='utf-8') as f:
        RESPONSES = json.load(f)
except Exception as e:
    logging.error(f"[CONFIG ERROR] Не удалось загрузить commands.json: {e}")
    RESPONSES = {}

@router.message(Command(commands=list(RESPONSES.keys())), F.reply_to_message)
async def handle_slash_command(message: Message):
    """
    Обрабатывает команды в ответ на сообщение, используя настройки из commands.json.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    text = message.text
    # Extract command without bot suffix
    command_name = text.lstrip("/").split("@")[0].lower()

    if command_name not in RESPONSES:
        logging.info(f"[UNKNOWN] Команда {command_name} не найдена.")
        return

    # Only admins and creators allowed
    member = await message.bot.get_chat_member(chat_id, user_id)
    if member.status not in ("administrator", "creator"):
        logging.info(f"[IGNORED] {message.from_user.full_name} ({member.status}) попытался использовать {message.text}.")
        return

    replied_msg = message.reply_to_message
    username_to_insert = f"@{replied_msg.from_user.username}" if replied_msg.from_user.username else replied_msg.from_user.full_name

    try:
        await message.delete()
        logging.info(f"[DELETE CMD] Команда /{command_name} удалена.")
    except Exception as e:
        logging.warning(f"[FAIL DELETE CMD] Не удалось удалить команду: {e}")

    tpl = RESPONSES.get(command_name, {})
    text_template = tpl.get("text", "")
    send_private = tpl.get("private", False)
    autodelete = tpl.get("autodelete", False)

    final_text = text_template.replace("{username}", username_to_insert)

    response_message = None

    if send_private:
        # Send response as private message
        try:
            await message.bot.send_message(replied_msg.from_user.id, final_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
            logging.info(f"[SENT PRIVATE] Ответ отправлен пользователю {username_to_insert}.")
        except Exception as e:
            logging.warning(f"[FAIL SEND PRIVATE] Не удалось отправить ответ в ЛС: {e}")
        # Delete question immediately if autodelete
        if autodelete:
            try:
                await message.bot.delete_message(chat_id, replied_msg.message_id)
                logging.info(f"[DELETE Q] Удалён вопрос (message_id={replied_msg.message_id}).")
            except Exception:
                pass
    else:
        # Send response in chat as reply
        try:
            response_message = await message.bot.send_message(
                chat_id,
                final_text,
                reply_to_message_id=replied_msg.message_id,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            logging.info(f"[SENT CHAT] Ответ в чат (message_id={response_message.message_id}).")
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
