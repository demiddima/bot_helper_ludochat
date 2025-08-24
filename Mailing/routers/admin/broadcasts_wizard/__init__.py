# routers/admin/broadcasts_wizard/__init__.py
# commit: collapse router aggregator here; provide PostWizard; keep public `router`
from __future__ import annotations
from aiogram import Router
from aiogram.fsm.state import StatesGroup, State

class PostWizard(StatesGroup):
    collecting = State()
    preview = State()
    title_wait = State()
    choose_kind = State()
    choose_audience = State()
    audience_ids_wait = State()
    audience_sql_wait = State()
    choose_schedule = State()

# include step routers
from .steps_collect_preview import router as _collect_preview
from .steps_audience_kind import router as _audience_kind
from .steps_schedule_finalize import router as _schedule_finalize

router = Router(name="admin_broadcasts_wizard")
router.include_router(_collect_preview)
router.include_router(_audience_kind)
router.include_router(_schedule_finalize)

__all__ = ["router", "PostWizard"]
