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

from config import PRIVATE_DESTINATIONS, LOG_CHANNEL_ID
from storage import (
    upsert_chat,
    add_user,
    add_membership,
    remove_membership,
    save_invite_link,
    get_all_invite_links,
    track_link_visit,
    has_terms_accepted as has_user_accepted,
    set_terms_accepted as set_user_accepted,
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
    # Запускаем очистку join_requests в фоне
    asyncio.create_task(cleanup_join_requests())
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
    uid = message.from_user.id

    # безопасная обёртка для трекинга
    async def _safe_track(link_key: str):
        try:
            await track_link_visit(link_key)
        except Exception as exc:
            logging.error(f"[TRACK] track_link_visit failed for {link_key}: {exc}")

    # 1) Если пользователь уже подтвердил — сразу выдаём ссылки
    if await has_user_accepted(uid):
    # трекинг клика, если есть параметр
        if len(parts) == 2 and parts[1] not in ("start",) and not parts[1].startswith("verify_"):
            asyncio.create_task(_safe_track(parts[1]))
        try:
            # только добавляем membership, не трогаем саму запись user
            await add_membership(uid, BOT_ID)
        except Exception as exc:
            await log_and_report(exc, f"add_membership_on_start({uid})")
        await send_invite_links(uid)
        return

    # 2) Flow "Я не бот" — пользователь нажал кнопку “Я согласен…”
    if len(parts) == 2 and parts[1].startswith("verify_"):
        orig_uid = int(parts[1].split("_", 1)[1])
        ts = join_requests.get(orig_uid)
        # таймаут 5 минут
        if ts is None or time.time() - ts > 300:
            join_requests.pop(orig_uid, None)
            await message.reply(
                "⏰ Время ожидания вышло. Отправьте /start ещё раз.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="/start",
                        url=f"https://t.me/{bot_username}?start=start"
                    )]
                ])
            )
            return

        join_requests.pop(orig_uid, None)
        try:
            await add_user_and_membership(message.from_user, BOT_ID)
        except Exception as exc:
            await log_and_report(exc, f"add_user({orig_uid})")

        # ставим флаг, что согласился
        try:
            await set_user_accepted(orig_uid)
        except Exception:
            logging.exception(f"[STORAGE] Не смогли записать terms_accepted для {orig_uid}")

        await send_invite_links(orig_uid)
        return

    # 3) Трекинг клика по старой ссылке (любая прочая метка)
    if len(parts) == 2 and parts[1] not in ("start",) and not parts[1].startswith("verify_"):
        asyncio.create_task(_safe_track(parts[1]))

    # 4) Обычный /start — показываем TERMS
    join_requests[uid] = time.time()
    try:
        await add_user_and_membership(message.from_user, BOT_ID)
    except Exception as exc:
        await log_and_report(exc, f"add_user_on_start({uid})")

    confirm_link = f"https://t.me/{bot_username}?start=verify_{uid}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Я согласен(а) и ознакомлен(а) со всем",
            url=confirm_link
        )]
    ])
    await bot.send_message(
        uid,
        TERMS_MESSAGE,
        reply_markup=kb,
        parse_mode="HTML",
        disable_web_page_preview=True
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
    all_links = await get_all_invite_links(uid)
    now = datetime.now(timezone.utc)

    triples: list[tuple[str, str, str]] = []
    expires_ts = int(time.time()) + 3600
    expires_dt_iso = (now + timedelta(hours=1)).isoformat()
    buttons: list[list[InlineKeyboardButton]] = []

    for dest in PRIVATE_DESTINATIONS:
        cid = dest["chat_id"]
        title = dest.get("title", "Chat")
        desc = dest.get("description", "")

        # Найти запись в БД
        db_item = next((item for item in all_links if item["chat_id"] == cid), None)
        link = db_item["invite_link"] if db_item else None

        # Парсим expires_at и делаем timezone-aware
        expires_at = None
        if db_item and db_item.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(db_item["expires_at"])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            except Exception:
                expires_at = None

        # Проверка членства
        is_member = False
        check_id = dest.get("check_id") if isinstance(dest.get("check_id"), int) else cid if isinstance(cid, int) else None
        if check_id is not None:
            try:
                m = await bot.get_chat_member(check_id, uid)
                if m.status in ("member", "administrator", "creator"):
                    is_member = True
            except TelegramAPIError:
                pass

        # Решаем, нужно ли создавать новую ссылку
        create_new = False
        if not link:
            create_new = True
        elif not is_member and expires_at and expires_at < now:
            create_new = True

        if create_new:
            if isinstance(cid, str) and cid.startswith("http"):
                link = cid
            else:
                invite = await bot.create_chat_invite_link(
                    chat_id=int(cid),
                    member_limit=1,
                    expire_date=expires_ts,
                    name=f"Invite for {uid}",
                    creates_join_request=False,
                )
                link = invite.invite_link

            # Подготовка числового chat_id для сохранения
            try:
                chat_id_for_db = int(cid)
            except (TypeError, ValueError):
                chat_id_for_db = None

            # Сохраняем только если chat_id корректен
            if chat_id_for_db is not None:
                try:
                    await save_invite_link(
                        uid,
                        chat_id_for_db,
                        link,
                        datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
                        expires_dt_iso
                    )
                except HTTPStatusError:
                    pass
                except Exception as exc:
                    logging.warning(f"[DB] Failed to save invite_link for chat_id={chat_id_for_db}: {exc}")

        triples.append((title, link, desc))
        buttons.append([InlineKeyboardButton(text=title, url=link)])

    # Кнопка обновления
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить ссылки", callback_data=f"refresh_{uid}")
    ])

    resources = "\n".join(f'<a href="{l}">{t}</a> — {d}' for t, l, d in triples)
    text = INVITE_TEXT_TEMPLATE.format(resources_list=resources)

    await bot.send_message(
        uid,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await bot.send_message(
        uid,
        MORE_INFO,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

    # Логирование
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
