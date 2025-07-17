import logging
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timezone, timedelta
from storage import get_all_invite_links, save_invite_link

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
            # Получаем все ссылки для пользователя
            existing_links = await get_all_invite_links(uid)
            existing_link_data = next((x for x in existing_links if x["chat_id"] == chat_id), None)

            # Логируем существующие ссылки для uid
            logging.info(f"[INFO] Существующие ссылки для {uid}: {existing_links}")

            # Если ссылка существует, проверяем срок действия
            if existing_link_data:
                link = existing_link_data["invite_link"]
                expires_at = existing_link_data.get("expires_at")

                if expires_at:
                    try:
                        # Преобразуем время из базы данных в формат с часовым поясом
                        exp = datetime.fromisoformat(expires_at).replace(tzinfo=timezone.utc)
                        current_time = datetime.now(timezone.utc)

                        # Если ссылка действительна, используем её
                        if exp > current_time:
                            links.append((title, link, desc))
                            buttons.append([{"text": title, "url": link}])
                            logging.info(f"[INFO] Ссылка для {title} актуальна, используем её.")
                            continue  # Пропускаем генерацию новой ссылки
                        else:
                            logging.info(f"[INFO] Ссылка для {title} устарела, генерируем новую.")
                    except Exception as e:
                        logging.warning(f"Ошибка при проверке срока действия ссылки для {title}: {e}")

            # Если ссылки нет или она устарела, генерируем новую
            if isinstance(chat_id, int):  # Если chat_id числовой, генерируем ссылку
                invite = await bot.create_chat_invite_link(
                    chat_id=chat_id,
                    member_limit=1,
                    creates_join_request=False,
                    name=f"Invite for {user.username or user.id}"  # Получаем username или id
                )
                invite_link = invite.invite_link

                # Добавляем сгенерированную ссылку в список
                links.append((title, invite_link, desc))
                buttons.append([{"text": title, "url": invite_link}])

                # Логируем перед сохранением
                logging.info(f"[INFO] Генерируем и сохраняем ссылку для {title}: {invite_link}")

                # Сохраняем сгенерированную ссылку в базу данных
                logging.info(f"[INFO] Перед сохранением ссылки для {title}: {invite_link}")
                save_result = await save_invite_link(
                    uid, chat_id, invite_link,
                    datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
                    (datetime.utcnow() + timedelta(hours=1)).isoformat()  # Ссылка действительна 1 час
                )

                # Логируем результат сохранения
                logging.info(f"[INFO] Результат сохранения ссылки: {save_result}")
            
            # Если chat_id - это ссылка (URL), используем её напрямую
            elif isinstance(chat_id, str) and chat_id.startswith("http"):
                links.append((title, chat_id, desc))
                buttons.append([{"text": title, "url": chat_id}])

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
                            invite_link = invite.invite_link
                            links.append((title, invite_link, desc))
                            buttons.append([{"text": title, "url": invite_link}])
                        except Exception as e2:
                            logging.warning(f"Не удалось создать invite после отзыва: {e2}")
                            try:
                                await bot.send_message(
                                    ERROR_LOG_CHANNEL_ID,
                                    f"Ошибка при повторном создании ссылки в чате {chat_id} "
                                    f"для пользователя {user.full_name} (@{user.username or 'нет'}, ID: {uid}): {e2}",
                                    parse_mode=None,
                                )
                            except:
                                logging.warning(f"Не удалось уведомить об ошибке invite повторно {uid}")
                    else:
                        logging.warning(f"Лимит invite-ссылок исчерпан в чате {chat_id}, но старых ссылок нет.")
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
                    logging.warning(f"Ошибка при управлении старыми ссылками в чате {chat_id}: {e3}")
                    try:
                        await bot.send_message(
                            ERROR_LOG_CHANNEL_ID,
                            f"Ошибка при работе со старыми ссылками в чате {chat_id}: {e3}",
                            parse_mode=None,
                        )
                    except:
                        logging.warning(f"[ERROR LOG] Не удалось уведомить об ошибке управления ссылками {chat_id}")
            else:
                logging.warning(f"Не удалось создать invite-ссылку для {user.full_name} (@{user.username or 'нет'}, ID: {uid}) в чате {chat_id}: {e}")
                try:
                    await bot.send_message(
                        ERROR_LOG_CHANNEL_ID,
                        f"Ошибка при создании invite-ссылки для {user.full_name} (@{user.username or 'нет'}, ID: {uid}) в чате {chat_id}: {e}",
                        parse_mode=None,
                    )
                except:
                    logging.warning(f"[ERROR LOG] Не удалось уведомить об ошибке invite для {chat_id}")
        except Exception as e:
            logging.warning(f"Непредвиденная ошибка при создании invite для {uid} в {chat_id}: {e}")
            try:
                await bot.send_message(
                    ERROR_LOG_CHANNEL_ID,
                    f"Непредвиденная ошибка при создании invite для {user.full_name} (@{user.username or 'нет'}, ID: {uid}) в чате {chat_id}: {e}",
                    parse_mode=None,
                )
            except:
                logging.warning(f"[ERROR LOG] Не удалось уведомить о непредвиденной ошибке invite {chat_id}")
    
    return links, buttons
