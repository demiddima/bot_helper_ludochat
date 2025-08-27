# Mailing/routers/__init__.py
# commit: fix(routers) — добавлен broadcasts_manager; явное подключение и лог
from aiogram import Router
import logging

router = Router(name="mailing")
log = logging.getLogger(__name__)

# Явные импорты: если что-то сломано — увидим стектрейс и быстро чиним
from .admin import broadcasts_wizard as _bw
from .admin import broadcasts_commands as _bc
from .admin import broadcasts_manager as _bm  # ← добавили менеджер

# Порядок важен: визард выше, чтобы /post гарантированно ловился здесь
router.include_router(_bw.router)
router.include_router(_bc.router)
router.include_router(_bm.router)  # ← подключили /broadcasts

log.info("[mailing] routers loaded: broadcasts_wizard, broadcasts_commands, broadcasts_manager")
