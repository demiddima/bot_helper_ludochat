import logging
import time
import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
    ChatMemberUpdated,
)
from aiogram.exceptions import TelegramAPIError
from httpx import HTTPStatusError

from config import PRIVATE_DESTINATIONS, LOG_CHANNEL_ID, ERROR_LOG_CHANNEL_ID
from storage import (
    upsert_chat,
    add_user,
    add_membership,
    remove_membership,
    save_invite_link,
    get_all_invite_links,
    track_link_visit,
)
from utils import log_and_report, join_requests, cleanup_join_requests, get_bot
from messages import TERMS_MESSAGE, INVITE_TEXT_TEMPLATE, MORE_INFO

router = Router()
BOT_ID: int | None = None

async def add_user_and_membership(user, chat_id):
    user_data = {
        "id": user.id,
        "username": user.username or None,
        "full_name": user.full_name or None,
    }
    await add_user(user_data)
    await add_membership(user.id, chat_id)

@router.startup()
async def on_startup():
    cleanup_join_requests()
    global BOT_ID
    bot = get_bot()
    me = await bot.get_me()
    BOT_ID = me.id
    try:
        await upsert_chat({
            "id": BOT_ID,
            "title": me.username or "bot",
            "type": "private",
            "added_at": datetime.utcnow().isoformat()
        })
    except Exception as exc:
        await log_and_report(exc, "upsert_chat(bot)")

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    bot = get_bot()
    parts = message.text.split()
    bot_username = (await bot.get_me()).username or ""

    # «Я не бот» flow
    if len(parts) == 2 and parts[1].startswith("verify_"):
        orig_uid = int(parts[1].split("_", 1)[1])
        ts = join_requests.get(orig_uid)
        if ts is None or time.time() - ts > 300:
            join_requests.pop(orig_uid, None)
            await message.reply(
                "⏰ Время ожидания вышло. Отправьте /start ещё раз.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(
                        text="/start",
                        url=f"https://t.me/{bot_username}?start=start"
                    )]]
                )
            )
            return
        join_requests.pop(orig_uid, None)
        try:
            await add_user_and_membership(message.from_user, BOT_ID)
        except Exception as exc:
            await log_and_report(exc, f"add_user({orig_uid})")
        await send_invite_links(orig_uid)
        return

    # Трекинг клика по старой ссылке
    if len(parts) == 2:
        asyncio.create_task(track_link_visit(parts[1]))

    # Обычный /start
    uid = message.from_user.id
    join_requests[uid] = time.time()
    try:
        await add_user_and_membership(message.from_user, BOT_ID)
    except Exception as exc:
        await log_and_report(exc, f"add_user_on_start({uid})")

    confirm_link = f"https://t.me/{bot_username}?start=verify_{uid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Я согласен(а) и ознакомлен(а) со всем",
            url=confirm_link
        )
    ]])
    await bot.send_message(
        uid, TERMS_MESSAGE,
        reply_markup=kb,
        parse_mode="HTML", disable_web_page_preview=True
    )

@router.callback_query(F.data.startswith("refresh_"))
async def on_refresh(query: CallbackQuery):
    await query.answer("Обновляю...")
    uid = int(query.data.split("_", 1)[1])
    if query.from_user.id != uid:
        return await query.answer("Это не ваши ссылки.")
    await send_invite_links(uid)

async def send_invite_links(uid: int):
    bot = get_bot()
    # Получаем все строки (expired + active)
    all_links = await get_all_invite_links(uid)
    existing_map = {item["chat_id"]: item["invite_link"] for item in all_links}

    triples = []
    expire_ts = int(time.time()) + 3600
    expire_dt = datetime.now(timezone.utc) + timedelta(hours=1)
    buttons = []

    for dest in PRIVATE_DESTINATIONS:
        cid = dest["chat_id"]
        title = dest.get("title", "Chat")
        desc = dest.get("description", "")

        check_id = dest.get("check_id") if isinstance(dest.get("check_id"), int) else (cid if isinstance(cid, int) else None)
        is_member = False
        if check_id is not None:
            try:
                m = await bot.get_chat_member(check_id, uid)
                if m.status in ("member", "administrator", "creator"):
                    is_member = True
            except TelegramAPIError:
                pass

        # Есть строка? (есть invite_link для этой пары в базе)
        if isinstance(cid, int) and cid in existing_map:
            if is_member:
                # Уже есть строка в базе и пользователь подписан — отдаем старую ссылку
                link = existing_map[cid]
            else:
                # Уже есть строка, но не подписан — НЕ создаём и НЕ сохраняем заново (чтобы не было дубликата)
                # Можно отправить ту же ссылку, либо вообще пропустить (зависит от бизнес-логики)
                link = existing_map[cid]
        else:
            # Нет строки — создаём новую ссылку
            if isinstance(cid, str) and cid.startswith("http"):
                link = cid
            else:
                invite = await bot.create_chat_invite_link(
                    chat_id=int(cid),
                    member_limit=1,
                    expire_date=expire_ts,
                    name=f"Invite for {uid}",
                    creates_join_request=False,
                )
                link = invite.invite_link
                # Сохраняем только если строки нет!
                try:
                    await save_invite_link(
                        uid,
                        cid,
                        link,
                        datetime.utcnow().isoformat(),
                        expire_dt.isoformat()
                    )
                except HTTPStatusError:
                    # дубликат — пропускаем (но по идее сюда не должны попасть)
                    pass
                except Exception as exc:
                    logging.warning(f"[DB] Не удалось сохранить invite_link для {cid}: {exc}")

        triples.append((title, link, desc))
        buttons.append([InlineKeyboardButton(text=title, url=link)])

    buttons.append([InlineKeyboardButton(text="🔄 Обновить ссылки", callback_data=f"refresh_{uid}")])
    resources = "\n".join(f'<a href="{l}">{t}</a> — {d}' for t, l, d in triples)
    text = INVITE_TEXT_TEMPLATE.format(resources_list=resources)

    await bot.send_message(
        uid, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML", disable_web_page_preview=True
    )
    await bot.send_message(
        uid, MORE_INFO,
        parse_mode="HTML", disable_web_page_preview=True
    )

    # Лог
    try:
        log_text = "🔗 <b>Ссылки сгенерированы</b>\n"
        log_text += f"Пользователь: <code>{uid}</code>\n"
        log_text += "\n".join(f"{t}: {l}" for t, l, _ in triples)
        await bot.send_message(LOG_CHANNEL_ID, log_text, parse_mode="HTML")
    except Exception as exc:
        logging.error(f"[LOG] {exc}")


@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    status = update.new_chat_member.status
    if status in ("left", "kicked"):
        join_requests.pop(update.from_user.id, None)
        try:
            await remove_membership(update.from_user.id, BOT_ID)
            logging.info(f"[MEMBERSHIP] Removed membership: user {update.from_user.id} -> bot {BOT_ID}")
        except Exception as exc:
            logging.warning(f"[WARNING] Failed to remove membership for user {update.from_user.id}: {exc}")
