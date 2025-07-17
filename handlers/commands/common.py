# handlers/commands/common.py

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

# Импортируем новую функцию из модуля resources
from handlers.join.resources import send_resources_message

router = Router(name="common")

@router.message(Command("update_links"), F.chat.type == "private")
async def cmd_update_links(message: Message):
    """
    Обновляет индивидуальные ресурсы (1 час, по PRIVATE_DESTINATIONS).
    """
    await message.answer("Обновляю ваши ресурсы…")
    try:
        # Раньше вызывали send_invite_links, теперь — send_resources_message
        await send_resources_message(message.from_user.id)
    except Exception as e:
        logging.error(f"[UPDATE_LINKS] {e}")
        await message.answer("Не удалось обновить ресурсы. Попробуйте позже.")

@router.message(Command("report_the_bug"), F.chat.type == "private")
async def cmd_report_bug(message: Message):
    """
    Сообщить о баге администратору.
    """
    await message.answer(
        "Если вы нашли ошибку, баг или неработающую кнопку, сообщите об этом сюда @admi_ludochat"
    )
