import logging
from aiogram.exceptions import TelegramBadRequest

async def generate_invite_links(bot, user, uid, PRIVATE_DESTINATIONS, verify_user, ERROR_LOG_CHANNEL_ID):
    links = []
    buttons = []
    for dest in PRIVATE_DESTINATIONS:
        if not all(k in dest for k in ("title", "chat_id", "description")):
            logging.error(f"[CONFIG ERROR] Некорректный PRIVATE_DESTINATIONS: {dest}")
            continue

        chat_id = dest["chat_id"]
        title = dest["title"]
        desc = dest["description"]

        try:
            invite = await bot.create_chat_invite_link(
                chat_id=chat_id,
                member_limit=1,
                creates_join_request=False,
                name=f"Invite for {user.username or user.id}"
            )
            try:
                verify_user(uid, invite.invite_link)
            except Exception as e:
                logging.error(f"[DB ERROR] Не удалось обновить invite_link для {uid}: {e}")
                try:
                    await bot.send_message(
                        ERROR_LOG_CHANNEL_ID,
                        f"Ошибка БД при обновлении invite_link пользователя {user.full_name} "
                        f"(@{user.username or 'нет'}, ID: {uid}): {e}",
                        parse_mode=None,
                    )
                except:
                    logging.warning(f"[ERROR LOG] Не удалось уведомить об ошибке invite_link {uid}")

            links.append((title, invite.invite_link, desc))
            buttons.append([{"text": title, "url": invite.invite_link}])
        except TelegramBadRequest as e:
            text_err = str(e).lower()
            if "limit" in text_err or "too many requests" in text_err or "invite links limit" in text_err:
                try:
                    old_links = await bot.get_chat_invite_links(chat_id=chat_id, limit=100)
                    if old_links:
                        oldest = old_links[0].invite_link
                        await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=oldest)
                        logging.info(f"[REVOKE] Отозвана старая ссылка {oldest} в чате {chat_id}")
                        try:
                            await bot.send_message(
                                ERROR_LOG_CHANNEL_ID,
                                f"Отозвана старая ссылка в чате {chat_id} для освобождения лимита.",
                                parse_mode=None,
                            )
                        except:
                            logging.warning(f"[ERROR LOG] Не удалось уведомить об отзыве ссылки {chat_id}")
                        try:
                            invite = await bot.create_chat_invite_link(
                                chat_id=chat_id,
                                member_limit=1,
                                creates_join_request=False,
                                name=f"Invite for {user.username or user.id}"
                            )
                            verify_user(uid, invite.invite_link)
                            links.append((title, invite.invite_link, desc))
                            buttons.append([{"text": title, "url": invite.invite_link}])
                        except Exception as e2:
                            logging.warning(f"[FAIL] Не удалось создать invite после отзыва: {e2}")
                            try:
                                await bot.send_message(
                                    ERROR_LOG_CHANNEL_ID,
                                    f"Ошибка при повторном создании ссылки в чате {chat_id} "
                                    f"для пользователя {user.full_name} (@{user.username or 'нет'}, ID: {uid}): {e2}",
                                    parse_mode=None,
                                )
                            except:
                                logging.warning(f"[ERROR LOG] Не удалось уведомить об ошибке invite повторно {uid}")
                    else:
                        logging.warning(f"[FAIL] Лимит invite-ссылок исчерпан в чате {chat_id}, но старых ссылок нет.")
                        try:
                            await bot.send_message(
                                ERROR_LOG_CHANNEL_ID,
                                f"Лимит invite-ссылок исчерпан в чате {chat_id}, "
                                f"но старые ссылки не найдены. Пользователь {user.full_name} "
                                f"(@{user.username or 'нет'}, ID: {uid}).",
                                parse_mode=None,
                            )
                        except:
                            logging.warning(f"[ERROR LOG] Не удалось уведомить о лимите invite {chat_id}")
                except Exception as e3:
                    logging.warning(f"[FAIL] Ошибка при управлении старыми ссылками в чате {chat_id}: {e3}")
                    try:
                        await bot.send_message(
                            ERROR_LOG_CHANNEL_ID,
                            f"Ошибка при работе со старыми ссылками в чате {chat_id}: {e3}",
                            parse_mode=None,
                        )
                    except:
                        logging.warning(f"[ERROR LOG] Не удалось уведомить об ошибке управления ссылками {chat_id}")
            else:
                logging.warning(f"[FAIL] Не удалось создать invite-ссылку для {user.full_name} (@{user.username or 'нет'}, ID: {uid}) в чате {chat_id}: {e}")
                try:
                    await bot.send_message(
                        ERROR_LOG_CHANNEL_ID,
                        f"Ошибка при создании invite-ссылки для {user.full_name} (@{user.username or 'нет'}, ID: {uid}) в чате {chat_id}: {e}",
                        parse_mode=None,
                    )
                except:
                    logging.warning(f"[ERROR LOG] Не удалось уведомить об ошибке invite для {chat_id}")
        except Exception as e:
            logging.warning(f"[FAIL] Непредвиденная ошибка при создании invite для {uid} в {chat_id}: {e}")
            try:
                await bot.send_message(
                    ERROR_LOG_CHANNEL_ID,
                    f"Непредвиденная ошибка при создании invite для {user.full_name} (@{user.username or 'нет'}, ID: {uid}) в чате {chat_id}: {e}",
                    parse_mode=None,
                )
            except:
                logging.warning(f"[ERROR LOG] Не удалось уведомить о непредвиденной ошибке invite {chat_id}")
    return links, buttons
