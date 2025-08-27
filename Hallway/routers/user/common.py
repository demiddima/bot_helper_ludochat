# Hallway/routers/user/common.py
# Коммит: ensure user_subscriptions on /update_links before regenerating invites

import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ParseMode

from Hallway.routers.join.resources import send_resources_message
from storage import ensure_user_subscriptions_defaults  # ← гарантируем запись в user_subscriptions

router = Router(name="common")


@router.message(Command("update_links"))
async def update_links(message: Message):
    """
    Обновляет инвайт-ссылки (refresh=True) и предварительно гарантирует,
    что пользователь занесён в user_subscriptions.
    """
    user = message.from_user
    uid = user.id
    func_name = "update_links"

    try:
        # 1) Ensure user_subscriptions (если нет записи — создаём дефолтную)
        try:
            await ensure_user_subscriptions_defaults(uid)
            logging.info(
                f"{func_name} – user_id={uid} – ensured user_subscriptions defaults.",
                extra={"user_id": uid},
            )
        except Exception as e:
            # Не блокируем обновление ссылок, просто логируем проблему ensure
            logging.error(
                f"{func_name} – user_id={uid} – ensure_user_subscriptions_defaults failed: {e}",
                extra={"user_id": uid},
            )

        # 2) Перегенерация инвайтов и отправка ресурсов
        await send_resources_message(
            message.bot,
            user,
            uid,
            refresh=True,  # Указываем, что нужно перегенерировать ссылки
        )
        logging.info(
            f"{func_name} – user_id={uid} – ссылки успешно обновлены.",
            extra={"user_id": uid},
        )

    except Exception as e:
        logging.error(
            f"{func_name} – user_id={uid} – ошибка при обновлении ссылок: {e}",
            extra={"user_id": uid},
        )
        try:
            await message.answer(
                "Произошла ошибка при обновлении ссылок.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as ee:
            logging.error(
                f"{func_name} – user_id={uid} – не удалось уведомить пользователя об ошибке: {ee}",
                extra={"user_id": uid},
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
            f"{func_name} – user_id={user_id} – отправлена инструкция по репорту багов.",
            extra={"user_id": user_id},
        )
    except Exception as e:
        logging.error(
            f"{func_name} – user_id={user_id} – ошибка при отправке инструкции по баг-репорту: {e}",
            extra={"user_id": user_id},
        )
