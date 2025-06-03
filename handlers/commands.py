import asyncio
import logging
import json
import os

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters.command import Command

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
    Обрабатывает команды /sell_account и /quit_gambling при ответе на сообщение.
    Для sell_account: удаляет команду и далее обе через таймаут.
    Для quit_gambling: не удаляет вопросы и ответы, просто отправляет ответ.
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
    username_to_insert = f"@{replied_msg.from_user.username}" if replied_msg.from_user.username else replied_msg.from_user.full_name

    # Delete the command message in both cases
    try:
        await message.delete()
        logging.info(f"[DELETE CMD] Команда /{command_name} удалена.")
    except Exception as e:
        logging.warning(f"[FAIL DELETE CMD] Не удалось удалить команду: {e}")

    tpl = RESPONSES.get(command_name, {})
    text_template = tpl.get("text", "")
    autodelete = tpl.get("autodelete", False)

    final_text = text_template.replace("{username}", username_to_insert)

    response_message = None

    # Send response in chat as reply using HTML parse mode
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

    # If sell_account, schedule deletion of question and answer
    if command_name == "sell_account" and autodelete:
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
