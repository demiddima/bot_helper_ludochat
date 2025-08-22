# services/db_api/__init__.py
from __future__ import annotations

from typing import Optional

from .base import BaseApi
from .users import UsersMixin
from .chats import ChatsMixin
from .memberships import MembershipsMixin
from .invite_links import InviteLinksMixin
from .algo import AlgoMixin
from .links import LinksMixin
from .subscriptions import SubscriptionsMixin
from .broadcasts import BroadcastsMixin


class DBApiClient(  # сохраняем то же имя класса
    UsersMixin,
    ChatsMixin,
    MembershipsMixin,
    InviteLinksMixin,
    AlgoMixin,
    LinksMixin,
    SubscriptionsMixin,
    BroadcastsMixin,
    BaseApi,
):
    """
    Итоговый клиент — множественное наследование от миксинов + BaseApi.
    Сигнатуры методов полностью совпадают со старым вариантом.
    """
    def __init__(self, api_url: Optional[str] = None, timeout: float = 10.0) -> None:
        super().__init__(api_url=api_url, timeout=timeout)


# Готовый singleton, как и раньше
db_api_client = DBApiClient()

__all__ = ["DBApiClient", "db_api_client"]
