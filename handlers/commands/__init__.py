from aiogram import Router

from .admin_commands import router as admin_commands_router
from .common import router as common_router
from .bug_report import router as bug_report_router

router = Router(name="commands")

# Подключаем маршруты для команд
router.include_router(admin_commands_router)  # команды для изменения HTML (advertisement_1, welcome, и т.д.)
router.include_router(common_router)           # команды для обновления ресурсов и отчётов о баге
router.include_router(bug_report_router)       # команда для сообщения о баге
