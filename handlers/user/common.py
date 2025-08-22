# common.py
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ParseMode

from handlers.join.resources import send_resources_message

router = Router(name="common")

@router.message(Command("update_links"))
async def update_links(message: Message):
    user = message.from_user
    uid = user.id
    func_name = "update_links"
    try:
        await send_resources_message(
            message.bot,
            user,
            uid,
            refresh=True,  # Указываем, что нужно перегенерировать ссылки
        )
        logging.info(
            f"user_id={uid} – Успешно обновлены ссылки.",
            extra={"user_id": uid}
        )
    except Exception as e:
        logging.error(
            f"user_id={uid} – Ошибка при обновлении ссылок: {e}",
            extra={"user_id": uid}
        )
        try:
            await message.answer("Произошла ошибка при обновлении ссылок.", parse_mode=ParseMode.HTML)
        except Exception as ee:
            logging.error(
                f"user_id={uid} – Не удалось уведомить пользователя об ошибке: {ee}",
                extra={"user_id": uid}
            )

@router.message(Command("report_the_bug"), F.chat.type == "private")
async def cmd_report_bug(message: Message):
    func_name = "cmd_report_bug"
    user_id = message.from_user.id
    try:
        await message.answer(
            "Если вы нашли ошибку, баг или неработающую кнопку, сообщите об этом сюда @admi_ludochat"
        )
        logging.info(
            f"user_id={user_id} – Отправлена инструкция по репорту багов.",
            extra={"user_id": user_id}
        )
    except Exception as e:
        logging.error(
            f"user_id={user_id} – Ошибка при отправке инструкции по баг-репорту: {e}",
            extra={"user_id": user_id}
        )
