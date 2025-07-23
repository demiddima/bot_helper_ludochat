from aiogram import Router

from .common import router as common_router
from .admin_texts import router as admin_texts_router

router = Router(name="commands")

# Подключаем маршруты для команд
router.include_router(common_router)           # команды для обновления ресурсов и отчётов о баге
router.include_router(admin_texts_router)      # команды для изменения HTML (advertisement_1, welcome, и т.д.)