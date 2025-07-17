import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from config import ID_ADMIN_USER
import messages

router = Router(name="admin_texts")

# Добавлены множества для новых файлов
_setwelcome_pending:       set[int] = set()
_setadvertisement_1_pending: set[int] = set()
_setadvertisement_2_pending: set[int] = set()
_setanonymity_pending:     set[int] = set()
_setwork_pending:          set[int] = set()
_setprojects_pending:      set[int] = set()
_setdoctors_pending:       set[int] = set()

def _text_command_handler(command_name: str, pending_set: set[int], file_path):
    """
    Генерирует два хэндлера:
      1) старт ожидания команды /set<command_name>
      2) приём текста и сохранение в файл
    """
    cmd = f"set{command_name}"

    @router.message(
        Command(cmd),
        F.from_user.id.in_(ID_ADMIN_USER),
        F.chat.type == "private"
    )
    async def start_handler(message: Message, cmd=cmd):
        await message.answer(f"📄 Пришлите новый HTML-текст для «{command_name}.html»")
        pending_set.add(message.from_user.id)

    @router.message(
        F.from_user.id.in_(pending_set),
        F.from_user.id.in_(ID_ADMIN_USER),
        F.chat.type == "private"
    )
    async def receive_handler(message: Message, path=file_path, cmd=cmd):
        new_text = message.text or ""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            await message.answer(f"✅ Файл «{command_name}.html» успешно обновлён и будет использоваться сразу.")
        except Exception as e:
            logging.error(f"[SET{cmd.upper()} ERROR] Не удалось сохранить {command_name}.html: {e}")
            await message.answer(f"❌ Ошибка при сохранении «{command_name}.html». Подробности в логах.")
        finally:
            pending_set.discard(message.from_user.id)

# Регистрируем команды на основе секций
_text_command_handler("welcome",       _setwelcome_pending,       messages.WELCOME_FILE)
_text_command_handler("advertisement_1", _setadvertisement_1_pending, "advertisement_1.html")
_text_command_handler("advertisement_2", _setadvertisement_2_pending, "advertisement_2.html")
_text_command_handler("anonymity",     _setanonymity_pending,     messages.ANONYMITY_FILE)
_text_command_handler("work",          _setwork_pending,          messages.WORK_FILE)
_text_command_handler("projects",      _setprojects_pending,      messages.PROJECTS_FILE)
_text_command_handler("doctors",       _setdoctors_pending,       messages.DOCTORS_FILE)
