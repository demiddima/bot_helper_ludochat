import asyncio
import logging
import json
import os
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters.command import Command

from config import ADMIN_CHAT_IDS, ERROR_LOG_CHANNEL_ID, ID_ADMIN_USER
from handlers.join import send_invite_links
import messages  # для доступа к MORE_INFO_FILE и DEFAULT_MORE_INFO

router = Router()

# Load command responses from commands.json
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # project root
commands_file = os.path.join(BASE_DIR, "commands.json")
try:
    with open(commands_file, "r", encoding="utf-8") as f:
        RESPONSES = json.load(f)
except Exception as e:
    logging.error(f"[CONFIG ERROR] Не удалось загрузить commands.json: {e}")
    RESPONSES = {}

# ---------------- existing handlers ----------------

@router.message(Command(commands=list(RESPONSES.keys())), F.reply_to_message)
async def handle_slash_command(message: Message):
    """
    Обрабатывает команды /sell_account и /quit_gambling при ответе на сообщение.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id not in ADMIN_CHAT_IDS:
        logging.info(f"[IGNORED] Команда в неразрешённом чате {chat_id}.")
        return

    command_name = message.text.lstrip("/").split("@")[0].lower()
    if command_name not in RESPONSES:
        logging.info(f"[UNKNOWN] Команда {command_name} не найдена.")
        return

    member = await message.bot.get_chat_member(chat_id, user_id)
    if member.status not in ("administrator", "creator"):
        logging.info(
            f"[IGNORED] {message.from_user.full_name} ({member.status}) "
            f"попытался использовать {message.text}."
        )
        return

    replied_msg = message.reply_to_message
    username_to_insert = (
        f"@{replied_msg.from_user.username}"
        if replied_msg.from_user.username
        else replied_msg.from_user.full_name
    )

    try:
        await message.delete()
    except Exception as e:
        logging.warning(f"[FAIL DELETE CMD] Не удалось удалить команду: {e}")

    tpl = RESPONSES[command_name]
    final_text = tpl.get("text", "").replace("{username}", username_to_insert)

    response_message = await message.bot.send_message(
        chat_id,
        final_text,
        reply_to_message_id=replied_msg.message_id,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    if command_name == "sell_account" and tpl.get("autodelete", False):
        async def delete_later():
            await asyncio.sleep(120)
            try:
                await message.bot.delete_message(chat_id, replied_msg.message_id)
            except:
                pass
            try:
                await message.bot.delete_message(chat_id, response_message.message_id)
            except:
                pass

        asyncio.create_task(delete_later())


@router.message(Command("update_links"), F.chat.type == "private")
async def cmd_update_links(message: Message):
    """
    Обновляет индивидуальные ссылки (1 час, по PRIVATE_DESTINATIONS).
    """
    await message.answer("Обновляю ваши ссылки…")
    try:
        await send_invite_links(message.from_user.id)
    except Exception as e:
        logging.error(f"[UPDATE_LINKS] {e}")
        await message.answer("Не удалось обновить ссылки. Попробуйте позже.")


@router.message(Command("report_the_bug"), F.chat.type == "private")
async def cmd_report_bug(message: Message):
    """
    Сообщить о баге администратору.
    """
    await message.answer(
        "Если вы нашли ошибку, баг или неработающую кнопку, сообщите об этом сюда @admi_ludochat"
    )

# --------------- new /setinfo handlers ----------------

# Множество admin-user, ожидающих ввода нового текста
_setinfo_pending: set[int] = set()

@router.message(
    Command("setinfo"),
    F.from_user.id.in_(ID_ADMIN_USER),
    F.chat.type == "private"
)
async def cmd_setinfo(message: Message):
    """
    Запускает режим обновления глобального MORE_INFO.
    Пришлите следующее сообщение с новым текстом.
    """
    await message.answer("📄 Пожалуйста, отправьте новый текст для MORE_INFO.")
    _setinfo_pending.add(message.from_user.id)


@router.message(
    F.from_user.id.in_(_setinfo_pending),
    F.from_user.id.in_(ID_ADMIN_USER),
    F.chat.type == "private"
)
async def process_setinfo(message: Message):
    """
    Принимает следующий текст от admin-user и сохраняет его в файл more_info.html.
    """
    new_text = message.text
    try:
        # Сохраняем новый текст
        with open(messages.MORE_INFO_FILE, "w", encoding="utf-8") as f:
            f.write(new_text)
        await message.answer("✅ Текст MORE_INFO успешно обновлён и будет использоваться сразу.")
    except Exception as e:
        logging.error(f"[SETINFO ERROR] Не удалось сохранить MORE_INFO: {e}")
        await message.answer("❌ Ошибка при сохранении. Подробности в логах.")
    finally:
        # Выходим из режима ожидания
        _setinfo_pending.discard(message.from_user.id)
