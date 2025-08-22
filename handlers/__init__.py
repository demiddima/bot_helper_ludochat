# handlers/__init__.py
# Единый явный реестр роутеров (без "тихих" try-импортов)

from aiogram import Router

# --- Админка ---
from .admin.admin_texts import router as admin_texts_router
from .admin.broadcasts_commands import router as admin_broadcasts_commands_router
from .admin.broadcasts_wizard import router as admin_broadcasts_wizard_router

# --- Пользовательские / общий ---
from .join import router as join_router          # включает start/resources/sections/membership
from .join.menu import router as menu_router     # меню подписок
from .user.common import router as user_common_router

router = Router(name="root")

# Порядок имеет значение, сначала админка
router.include_router(admin_texts_router)
router.include_router(admin_broadcasts_commands_router)
router.include_router(admin_broadcasts_wizard_router)

# Затем пользовательские
router.include_router(join_router)
router.include_router(menu_router)
router.include_router(user_common_router)
