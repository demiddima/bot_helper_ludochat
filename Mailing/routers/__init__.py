from aiogram import Router

router = Router(name="mailing")

try:
    from .admin.broadcasts_commands import router as broadcasts_commands_router
    router.include_router(broadcasts_commands_router)
except Exception:
    pass

try:
    from .admin.broadcasts_wizard import router as broadcasts_wizard_router
    router.include_router(broadcasts_wizard_router)
except Exception:
    pass
