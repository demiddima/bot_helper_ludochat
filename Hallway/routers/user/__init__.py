from aiogram import Router
from .common import router as common_router

# Единый роутер пользовательских хендлеров
router = Router(name="hallway_user")
router.include_router(common_router)
