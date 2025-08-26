# common/middlewares/albums.py
# Commit: fix(albums): буферизация media_group — один вызов хендлера на группу

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Dict, List, Tuple

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class AlbumsMiddleware(BaseMiddleware):
    """
    Копит сообщения одной media_group и пропускает дальше только последний апдейт.
    Полный список сообщений группы доступен в data['album']: List[Message].
    """

    def __init__(self, wait: float = 0.6):
        self.wait = wait
        self._buffers: Dict[Tuple[int, str], List[Message]] = defaultdict(list)

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)

        key = (event.chat.id, event.media_group_id)
        self._buffers[key].append(event)

        # даём Телеграму прислать все части альбома
        await asyncio.sleep(self.wait)

        buf = self._buffers.get(key, [])
        if buf and buf[-1].message_id == event.message_id:
            data["album"] = buf
            self._buffers.pop(key, None)
            return await handler(event, data)

        # промежуточные апдейты глушим
        return
