# Mailing/services/broadcasts/sender/__init__.py
# commit: refactor(sender/__init__): удалить send_content_json и мёртвые реэкспорты; оставить публичный API

from .facade import (
    send_preview,
    send_actual,
)
from .policy import CAPTION_LIMIT

__all__ = [
    "send_preview",
    "send_actual",
    "CAPTION_LIMIT",
]
