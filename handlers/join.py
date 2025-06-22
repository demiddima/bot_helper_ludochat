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
    Update,
)
from aiogram.exceptions import TelegramAPIError

from config import PRIVATE_DESTINATIONS, LOG_CHANNEL_ID, ERROR_LOG_CHANNEL_ID, INVITE_LINK_MODE
from storage import (
    upsert_chat,
    add_user,
    add_membership,
    remove_membership,
    save_invite_link,
    get_invite_links,
    delete_invite_links,
    track_link_visit,
)
from utils import log_and_report, join_requests, cleanup_join_requests, get_bot
from messages import TERMS_MESSAGE, INVITE_TEXT_TEMPLATE, MORE_INFO

router = Router()
BOT_ID: int | None = None
_last_refresh: dict[int, float] = {}

async def add_user_and_membership(user, chat_id):
    user_data = {
        "id": user.id,
        "username": user.username or None,
        "full_name": user.full_name or None,
    }
    await add_user(user_data)
    await add_membership(user.id, chat_id)

async def get_valid_invite_links(user_id):
    now = datetime.utcnow()
    links = await get_invite_links(user_id)
    result: list[tuple[int, str]] = []
    for link in links:
        expires = datetime.fromisoformat(link['expires_at']).replace(tzinfo=None)
        if expires > now:
            result.append((link['chat_id'], link['invite_link']))
    return result

@router.startup()
async def on_startup():
    def handle_asyncio_exception(loop, context):
        bot = get_bot()
        err = context.get("exception") or context.get("message")
        text = f"⚠️ <b>Asyncio Exception:</b> <pre>{err}</pre>"
        asyncio.create_task(bot.send_message(ERROR_LOG_CHANNEL_ID, text, parse_mode="HTML"))
    asyncio.get_event_loop().set_exception_handler(handle_asyncio_exception)
    
    global BOT_ID
    bot = get_bot()
    me = await bot.get_me()
    BOT_ID = me.id
    try:
        await upsert_chat({
            "id": BOT_ID,
            "title": me.username or "bot",
            "type": "bot"
        })
    except Exception as exc:
        await log_and_report(exc, "upsert_chat(bot)")
    cleanup_join_requests()

@router.message(F.text.startswith("/start"))
async def process_start(message: Message):
    bot = get_bot()
    parts = message.text.split()
    bot_username = (await bot.get_me()).username or ""

    if len(parts) == 2 and parts[1].startswith("verify_"):
        orig_uid = int(parts[1].split("_", 1)[1])
        ts = join_requests.get(orig_uid)
        if ts is None or time.time() - ts > 300:
            join_requests.pop(orig_uid, None)
            await message.reply(
                "⏰ Время ожидания вышло. Отправьте /start ещё раз.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(
                        text="/start",
                        url=f"https://t.me/{bot_username}?start=start"
                    )]]
                )
            )
            return

        join_requests.pop(orig_uid, None)
        try:
            u = message.from_user
            await add_user_and_membership(u, BOT_ID)
        except Exception as exc:
            await log_and_report(exc, f"add_user({orig_uid})")
        await send_invite_links(orig_uid)
        return

    if len(parts) == 2:
        link_key = parts[1]
        async def tracked_task():
            try:
                await track_link_visit(link_key)
            except Exception as exc:
                bot = get_bot()
                text = (
                    f"🚨 <b>Ошибка в track_link_visit</b>\n"
                    f"<pre>{repr(exc)}</pre>\n"
                    f"<b>link_key:</b> <code>{link_key}</code>"
                )
                await bot.send_message(ERROR_LOG_CHANNEL_ID, text, parse_mode="HTML")
        asyncio.create_task(tracked_task())

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
        uid,
        TERMS_MESSAGE,
        reply_markup=kb,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

@router.callback_query(F.data.startswith("refresh_"))
async def on_refresh(query: CallbackQuery):
    await query.answer("Обновляю...")
    _, uid_str = query.data.split("_", 1)
    uid = int(uid_str)
    if query.from_user.id != uid:
        return await query.answer("Это не ваши ссылки.")
    await send_invite_links(uid)

async def send_invite_links(uid: int):
    bot = get_bot()
    now = time.time()
    if now - _last_refresh.get(uid, 0) < 10:
        return
    _last_refresh[uid] = now

    # отзываем старые ссылки
    existing = await get_valid_invite_links(uid)
    for chat_id, link in existing:
        try:
            await bot.revoke_chat_invite_link(chat_id, link)
        except TelegramAPIError:
            pass
    await delete_invite_links(uid)

    triples: list[tuple[str, str, str]] = []
    expire_ts = int(time.time()) + 3600  # 1 час
    expire_dt = datetime.now(timezone.utc) + timedelta(hours=1)
    buttons: list[list[InlineKeyboardButton]] = []

    for dest in PRIVATE_DESTINATIONS:
        cid = dest['chat_id']
        title = dest.get('title', 'Chat')
        desc = dest.get('description', '')
        # --- РЕЖИМЫ: static — используем ссылку, dynamic — генерируем ---
        if INVITE_LINK_MODE == "static" and str(cid).startswith("http"):
            # Просто используем существующую ссылку
            triples.append((title, cid, desc))
            buttons.append([InlineKeyboardButton(text=title, url=cid)])
        elif INVITE_LINK_MODE == "dynamic":
            try:
                invite = await bot.create_chat_invite_link(
                    chat_id=int(cid),
                    member_limit=1,
                    expire_date=expire_ts,
                    name=f"Invite for {uid}",
                    creates_join_request=False,
                )
                now_str = datetime.utcnow().isoformat()
                expires_str = expire_dt.isoformat()
                await save_invite_link(uid, int(cid), invite.invite_link, now_str, expires_str)
                triples.append((title, invite.invite_link, desc))
                buttons.append([InlineKeyboardButton(text=title, url=invite.invite_link)])
            except TelegramAPIError as exc:
                logging.warning(f"Failed to create link for {cid}: {exc}")
        # fallback для неправильного значения/режима
        else:
            continue

    buttons.append([InlineKeyboardButton(text="🔄 Обновить ссылки", callback_data=f"refresh_{uid}")])

    # формируем блок ссылок и подставляем в шаблон
    resources_lines = "\n".join(
        f'<a href="{link}">{title}</a> — {desc}' for title, link, desc in triples
    )
    text = INVITE_TEXT_TEMPLATE.format(resources_list=resources_lines)
    await bot.send_message(
        uid,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await bot.send_message(
        uid,
        MORE_INFO,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    try:
        log_text = (
            f"🔗 <b>Ссылки сгенерированы</b>\n"
            f"Пользователь: <code>{uid}</code>\n"
            + "\n".join([f"{title}: {link}" for title, link, _ in triples])
        )
        await bot.send_message(
            LOG_CHANNEL_ID,
            log_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as log_exc:
        logging.error(f"[LOG] Failed to send log to channel {LOG_CHANNEL_ID}: {log_exc}")

@router.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    status = update.new_chat_member.status
    if status in ("left", "kicked"):
        join_requests.pop(update.from_user.id, None)
        try:
            await remove_membership(update.from_user.id, BOT_ID)
            logging.info(
                f"[MEMBERSHIP] Removed membership: user {update.from_user.id} -> bot {BOT_ID}"
            )
        except Exception as exc:
            logging.warning(
                f"[WARNING] Failed to remove membership for user {update.from_user.id}: {exc}"
            )
