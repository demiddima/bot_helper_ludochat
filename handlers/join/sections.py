# handlers/join/sections.py

from aiogram import Router, F
from aiogram.types import CallbackQuery
import messages

router = Router()

@router.callback_query(F.data == "section_work")
async def section_work(query: CallbackQuery):
    await query.message.edit_text(
        messages.get_work_text(),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=query.message.reply_markup
    )

@router.callback_query(F.data == "section_anonymity")
async def section_anonymity(query: CallbackQuery):
    await query.message.edit_text(
        messages.get_anonymity_text(),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=query.message.reply_markup
    )

@router.callback_query(F.data == "section_projects")
async def section_projects(query: CallbackQuery):
    await query.message.edit_text(
        messages.get_projects_text(),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=query.message.reply_markup
    )

@router.callback_query(F.data == "section_doctors")
async def section_doctors(query: CallbackQuery):
    await query.message.edit_text(
        messages.get_doctors_text(),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=query.message.reply_markup
    )
