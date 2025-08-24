# Mailing/services/broadcasts/sender/__init__.py
# Тонкий __init__: только публичный API и реэкспорты. Вся логика — в facade.py.

from .facade import (
    send_preview,
    send_content_json,
    send_media,
    send_html,
)

from .policy import CAPTION_LIMIT

__all__ = [
    "send_preview",
    "send_content_json",
    "send_media",
    "send_html",
    "CAPTION_LIMIT",
]
