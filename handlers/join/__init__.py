from aiogram import Router

from .membership import router as membership_router
from .start      import router as start_router
from .resources  import router as resources_router
from .sections   import router as sections_router

router = Router(name="join")
router.include_router(membership_router)
router.include_router(start_router)
router.include_router(resources_router)
router.include_router(sections_router)
