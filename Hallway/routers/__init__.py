from aiogram import Router
from .join import router as join_router
from .user import router as user_router
from .admin import router as admin_router

router = Router(name="hallway")
router.include_router(join_router)
router.include_router(user_router)
router.include_router(admin_router)
