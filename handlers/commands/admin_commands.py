import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from config import ID_ADMIN_USER
import messages

router = Router(name="admin_commands")

# Множества ожидающих ввода по каждому типу
_pending = {
    "welcome":      set(),
    "anonymity":    set(),
    "work":         set(),
    "projects":     set(),
    "doctors":      set(),
    "advertisement_1": set(),
    "advertisement_2": set(),
}

# Отображение имени команды → файл шаблона из messages.py
FILES = {
    "welcome":       messages.WELCOME_FILE,
    "anonymity":     messages.ANONYMITY_FILE,
    "work":          messages.WORK_FILE,
    "projects":      messages.PROJECTS_FILE,
    "doctors":       messages.DOCTORS_FILE,
    "advertisement_1": "advertisement_1.html",
    "advertisement_2": "advertisement_2.html",
}

def setup_command(name: str, label: str):
    @router.message(
        Command(f"set{name}"),
        F.from_user.id.in_(ID_ADMIN_USER),
        F.chat.type == "private"
    )
    async def _set(message: Message, cmd=name, lbl=label):
        await message.answer(f"📄 Пришлите новый HTML-текст для «{lbl}».")
        _pending[cmd].add(message.from_user.id)

    @router.message(
        F.from_user.id.in_(_pending[name]),
        F.from_user.id.in_(ID_ADMIN_USER),
        F.chat.type == "private"
    )
    async def _process(message: Message, cmd=name, lbl=label):
        new_text = message.text or ""
        try:
            path = FILES[cmd]
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            await message.answer(f"✅ Файл «{lbl}» успешно обновлён и будет использоваться сразу.")
        except Exception as e:
            logging.error(f"[SET_{cmd.upper()} ERROR] Не удалось сохранить «{lbl}»: {e}")
            await message.answer(f"❌ Ошибка при сохранении «{lbl}». Подробности в логах.")
        finally:
            _pending[cmd].discard(message.from_user.id)

# Инициализация всех команд
setup_command("welcome",       "welcome.html")
setup_command("anonymity",     "anonymity.html")
setup_command("work",          "work.html")
setup_command("projects",      "projects.html")
setup_command("doctors",       "doctors.html")
setup_command("advertisement_1", "advertisement_1.html")
setup_command("advertisement_2", "advertisement_2.html")
