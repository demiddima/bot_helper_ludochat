# sections.py
# Обновление: Приведение к корпоративному стилю логирования — [function] – user_id=… – описание. Все рисковые операции обёрнуты в try/except.

from aiogram import Router, F
from aiogram.types import CallbackQuery
import messages
import logging
import re

router = Router()

# Функция для нормализации текста: удаление лишних пробелов, символов новой строки и HTML-тегов
def normalize_text(text):
    # Убираем все HTML теги
    text_without_html = re.sub(r'<.*?>', '', text)
    # Удаляем лишние пробелы и символы новой строки
    return re.sub(r'\s+', ' ', text_without_html.strip())

# Функция для проверки изменений контента
def is_message_modified(current_text, new_text, current_markup, new_markup):
    """
    Проверяет, изменился ли контент (текст) или клавиатура.
    """
    if current_text != new_text:
        return True
    if current_markup != new_markup:
        return True
    return False

@router.callback_query(F.data == "section_work")
async def section_work(query: CallbackQuery):
    uid = query.from_user.id
    func_name = "section_work"
    current_text = query.message.text
    current_markup = query.message.reply_markup

    # Новый текст и разметка, которые мы хотим установить
    new_text = messages.get_work_text()
    new_markup = query.message.reply_markup

    # Нормализуем текущий текст и новый текст
    normalized_current_text = normalize_text(current_text)
    normalized_new_text = normalize_text(new_text)

    # Проверка на изменение текста и разметки
    if not is_message_modified(normalized_current_text, normalized_new_text, current_markup, new_markup):
        logging.info(f"user_id={uid} – Контент не изменился. Игнорируем.", extra={"user_id": uid})
        return  # Если сообщение не изменилось, игнорируем запрос

    try:
        logging.info(f"user_id={uid} – нажата секция section_work", extra={"user_id": uid})
        await query.message.edit_text(
            new_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=new_markup
        )
    except Exception as e:
        logging.error(f"user_id={uid} – Ошибка при обработке секции section_work: {e}", extra={"user_id": uid})

@router.callback_query(F.data == "section_anonymity")
async def section_anonymity(query: CallbackQuery):
    uid = query.from_user.id
    func_name = "section_anonymity"
    current_text = query.message.text
    current_markup = query.message.reply_markup

    new_text = messages.get_anonymity_text()
    new_markup = query.message.reply_markup

    # Нормализуем текущий текст и новый текст
    normalized_current_text = normalize_text(current_text)
    normalized_new_text = normalize_text(new_text)

    if not is_message_modified(normalized_current_text, normalized_new_text, current_markup, new_markup):
        logging.info(f"user_id={uid} – Контент не изменился. Игнорируем.", extra={"user_id": uid})
        return  # Если сообщение не изменилось, игнорируем запрос

    try:
        logging.info(f"user_id={uid} – нажата секция section_anonymity", extra={"user_id": uid})
        await query.message.edit_text(
            new_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=new_markup
        )
    except Exception as e:
        logging.error(f"user_id={uid} – Ошибка при обработке секции section_anonymity: {e}", extra={"user_id": uid})

@router.callback_query(F.data == "section_projects")
async def section_projects(query: CallbackQuery):
    uid = query.from_user.id
    func_name = "section_projects"
    current_text = query.message.text
    current_markup = query.message.reply_markup

    new_text = messages.get_projects_text()
    new_markup = query.message.reply_markup

    # Нормализуем текущий текст и новый текст
    normalized_current_text = normalize_text(current_text)
    normalized_new_text = normalize_text(new_text)

    if not is_message_modified(normalized_current_text, normalized_new_text, current_markup, new_markup):
        logging.info(f"user_id={uid} – Контент не изменился. Игнорируем.", extra={"user_id": uid})
        return  # Если сообщение не изменилось, игнорируем запрос

    try:
        logging.info(f"user_id={uid} – нажата секция section_projects", extra={"user_id": uid})
        await query.message.edit_text(
            new_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=new_markup
        )
    except Exception as e:
        logging.error(f"user_id={uid} – Ошибка при обработке секции section_projects: {e}", extra={"user_id": uid})

@router.callback_query(F.data == "section_doctors")
async def section_doctors(query: CallbackQuery):
    uid = query.from_user.id
    func_name = "section_doctors"
    current_text = query.message.text
    current_markup = query.message.reply_markup

    new_text = messages.get_doctors_text()
    new_markup = query.message.reply_markup

    # Нормализуем текущий текст и новый текст
    normalized_current_text = normalize_text(current_text)
    normalized_new_text = normalize_text(new_text)

    if not is_message_modified(normalized_current_text, normalized_new_text, current_markup, new_markup):
        logging.info(f"user_id={uid} – Контент не изменился. Игнорируем.", extra={"user_id": uid})
        return  # Если сообщение не изменилось, игнорируем запрос

    try:
        logging.info(f"user_id={uid} – нажата секция section_doctors", extra={"user_id": uid})
        await query.message.edit_text(
            new_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=new_markup
        )
    except Exception as e:
        logging.error(f"user_id={uid} – Ошибка при обработке секции section_doctors: {e}", extra={"user_id": uid})

@router.callback_query(F.data == "section_advertisement")
async def section_advertisement(query: CallbackQuery):
    uid = query.from_user.id
    func_name = "section_advertisement"
    current_text = query.message.text
    current_markup = query.message.reply_markup

    # Новый текст и разметка
    new_text = messages.get_ad_text()
    new_markup = query.message.reply_markup

    # Нормализуем и проверяем изменения
    normalized_current = normalize_text(current_text)
    normalized_new = normalize_text(new_text)
    if not is_message_modified(normalized_current, normalized_new, current_markup, new_markup):
        logging.info(f"user_id={uid} – Контент не изменился. Игнорируем.", extra={"user_id": uid})
        return

    try:
        logging.info(f"user_id={uid} – нажата секция section_advertisement", extra={"user_id": uid})
        # Редактируем сообщение, вставляя рекламный текст
        await query.message.edit_text(
            new_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=new_markup
        )
    except Exception as e:
        logging.error(
            f"user_id={uid} – Ошибка при обработке секции section_advertisement: {e}",
            extra={"user_id": uid}
        )