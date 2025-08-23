# handlers/admin/broadcasts_commands.py
from __future__ import annotations

import logging
from typing import Dict, Any, List

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from config import ID_ADMIN_USER
from services.db_api_client import db_api_client
from services.broadcasts import get_due_broadcasts, send_broadcast, mark_broadcast_sent

router = Router(name="admin_broadcasts_commands")
log = logging.getLogger(__name__)


@router.message(
    Command("broadcasts_due"),
    F.from_user.id.in_(ID_ADMIN_USER),
    F.chat.type == "private",
)
async def cmd_broadcasts_due(message: Message):
    try:
        due = await get_due_broadcasts(limit=50)
        if not due:
            return await message.answer("Пока нет запланированных к отправке.")
        lines = [f"#{b['id']} [{b['kind']}] {b['title']} @ {b.get('scheduled_at')}" for b in due[:20]]
        await message.answer("Готовы к отправке:\n" + "\n".join(lines))
    except Exception as e:
        log.error(
            "Админ-команда /broadcasts_due: ошибка — user_id=%s, ошибка=%s",
            message.from_user.id, e, extra={"user_id": message.from_user.id}
        )
        try:
            await message.answer("❌ Ошибка при получении списка рассылок.")
        except Exception:
            pass


@router.message(
    Command("broadcast_send"),
    F.from_user.id.in_(ID_ADMIN_USER),
    F.chat.type == "private",
)
async def cmd_broadcast_send(message: Message, command: CommandObject):
    try:
        parts = (message.text or "").split()
        if len(parts) < 2 or not parts[1].isdigit():
            return await message.answer("Использование: /broadcast_send <id>")

        bid = int(parts[1])
        b = await db_api_client.get_broadcast(bid)
        if not b or b.get("status") not in ("scheduled", "draft"):
            return await message.answer("Эта рассылка не в статусе scheduled/draft или не найдена.")

        sent, failed = await send_broadcast(message.bot, b)
        if sent > 0:
            await mark_broadcast_sent(bid)
        await message.answer(f"Готово: id={bid}, sent={sent}, failed={failed}")
    except Exception as e:
        log.error(
            "Админ-команда /broadcast_send: ошибка — user_id=%s, ошибка=%s",
            message.from_user.id, e, extra={"user_id": message.from_user.id}
        )
        try:
            await message.answer("❌ Ошибка при отправке рассылки.")
        except Exception:
            pass


@router.message(
    Command("broadcast_preview"),
    F.from_user.id.in_(ID_ADMIN_USER),
    F.chat.type == "private",
)
async def cmd_broadcast_preview(message: Message, command: CommandObject):
    """Показывает размер аудитории по текущему таргету."""
    try:
        if not command.args or not command.args.strip().isdigit():
            return await message.answer("Формат: /broadcast_preview <id>")
        bid = int(command.args.strip())

        tgt = await db_api_client.get_broadcast_target(bid)
        if tgt["type"] == "ids":
            norm = {"type": "ids", "user_ids": tgt.get("user_ids") or []}
        elif tgt["type"] == "sql":
            norm = {"type": "sql", "sql": tgt.get("sql") or ""}
        else:
            norm = {"type": "kind", "kind": tgt.get("kind")}

        prev = await db_api_client.audience_preview(norm, limit=10000)
        sample = ", ".join(map(str, prev.get("sample", [])[:10])) if prev.get("sample") else ""
        tail = f"\nПример: <code>{sample}</code>" if sample else ""
        await message.answer(f"🔍 #{bid}: всего <b>{prev['total']}</b>{tail}")
    except Exception as e:
        log.error(
            "Админ-команда /broadcast_preview: ошибка — user_id=%s, ошибка=%s",
            message.from_user.id, e, extra={"user_id": message.from_user.id}
        )
        try:
            await message.answer("❌ Ошибка при предпросмотре аудитории.")
        except Exception:
            pass


@router.message(
    Command("broadcast_status"),
    F.from_user.id.in_(ID_ADMIN_USER),
    F.chat.type == "private",
)
async def cmd_broadcast_status(message: Message, command: CommandObject):
    """Сводка доставок по рассылке."""
    try:
        if not command.args or not command.args.strip().isdigit():
            return await message.answer("Формат: /broadcast_status <id>")
        bid = int(command.args.strip())

        rows: List[Dict[str, Any]] = await db_api_client.list_deliveries(bid, limit=200)
        total = len(rows)
        sent = sum(1 for r in rows if r["status"] == "sent")
        failed = sum(1 for r in rows if r["status"] == "failed")
        pending = sum(1 for r in rows if r["status"] == "pending")
        skipped = sum(1 for r in rows if r["status"] == "skipped")

        errs = [r for r in rows if r["status"] == "failed"][:5]
        tail = ""
        if errs:
            tail = "\n\nПоследние ошибки:\n" + "\n".join(
                f"• {e['user_id']}: {e.get('error_code') or ''} {e.get('error_message') or ''}".strip()
                for e in errs
            )

        await message.answer(
            f"📊 Статус #{bid}\n"
            f"Всего: {total} | sent: {sent} | failed: {failed} | pending: {pending} | skipped: {skipped}{tail}"
        )
    except Exception as e:
        log.error(
            "Админ-команда /broadcast_status: ошибка — user_id=%s, ошибка=%s",
            message.from_user.id, e, extra={"user_id": message.from_user.id}
        )
        try:
            await message.answer("❌ Ошибка при получении статуса рассылки.")
        except Exception:
            pass
