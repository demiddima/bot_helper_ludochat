from aiogram import Router

# Подмодули прихожей
from .membership import router as membership_router
from .start import router as start_router
from .menu import router as menu_router
from .resources import router as resources_router
from .sections import router as sections_router

# Единый роутер для блока Join
router = Router(name="hallway_join")
router.include_router(membership_router)
router.include_router(start_router)
router.include_router(menu_router)
router.include_router(resources_router)
router.include_router(sections_router)
