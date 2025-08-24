# package
from aiogram import Router
from .admin_texts import router as admin_texts_router

# Единый роутер админки Hallway
router = Router(name="hallway_admin")
router.include_router(admin_texts_router)
