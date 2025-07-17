from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

router = Router(name="bug_report")

@router.message(Command("report_the_bug"), F.chat.type == "private")
async def cmd_report_bug(message: Message):
    await message.answer(
        "Если вы нашли ошибку, баг или неработающую кнопку, сообщите об этом сюда @admi_ludochat"
    )
