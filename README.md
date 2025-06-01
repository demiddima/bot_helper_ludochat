# Request Processor Bot v10 (Markdown)

**Данная версия включает:**
- Встроенные Markdown-ссылки во втором сообщении.
- Кнопка “✅ Я согласен(а) и ознакомлен(а) со всем” открывает бота с `/start verify_<user_id>`.
- Обработка edge-case: повторный `/start`, ошибки в БД, отсутствие DM и т.д.

## Структура проекта

```
request-processor-bot-v10-markdown/
├── README.md
├── requirements.txt
├── config.py
├── storage.py
├── main.py
├── set_admin_commands.py
└── handlers/
    ├── join.py
    └── commands.py
```

### Настройка

1. **config.py**  
   - `BOT_TOKEN` — ваш токен бота.  
   - `PUBLIC_CHAT_ID` — ID публичного чата, куда приходят заявки (нажали «Вступить»).  
   - `LOG_CHANNEL_ID` — ID канала для логирования.  
   - `PRIVATE_DESTINATIONS` — список приватных чатов, куда выдаём персональные ссылки (title, chat_id, description).  
   - `ADMIN_CHAT_IDS` — список ID чатов, в которых бот – админ (для установки slash-команд).

2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

3. Запустите бота:
   ```bash
   python main.py
   ```
   При запуске бот автоматически задаст админские команды `/sell_account` и `/quit_gambling` в чатах из `ADMIN_CHAT_IDS`.

4. (Опционально) Чтобы вручную обновить команды без перезапуска:
   ```bash
   python set_admin_commands.py
   ```

---

## Как работает бот

1. **Вступление и проверка**  
   - Пользователь нажимает «Вступить» в `PUBLIC_CHAT_ID`.  
   - Бот сохраняет join-запрос и отправляет ЛС сообщение с условиями и кнопкой:  
     ```
     https://t.me/<BotUsername>?start=verify_<USER_ID>
     ```  
   - При клике Telegram откроет личный чат с ботом и отправит `/start verify_<USER_ID>`.

2. **Обработка `/start verify_<USER_ID>`**  
   - Если payload корректен и `uid` есть в `join_requests`, бот одобряет заявку, сохраняет пользователя в SQLite (`is_verified=0` → `1`), создаёт персональные invite-ссылки и отправляет второе сообщение.  
   - Если DM недоступен, бот публикует ссылку и текст во `PUBLIC_CHAT_ID`.  
   - Лог события отправляется в `LOG_CHANNEL_ID`.

3. **Второе сообщение**  
   - Содержит список проектов с встроенными Markdown-ссылками:
     ```
     **Здесь находятся все ссылки на проекты сообщества «Лудочат»**

     [Лудочат · помощь игрокам](https://t.me/+as3JmHK21sxhMGEy) — чат взаимовыручки …

     [Серый Лудочат](https://t.me/GrayLudoChat) — …

     **Приватные чаты:**

     [12 шагов](https://t.me/Ludo12Steps) — …

     [Поп-психология](https://t.me/LudoPopPsych) — …

     [Научно доказанные методы лечения](https://t.me/LudoScience) — …

     [Тест](<test_link>) — тестовая индивидуальная ссылка

     **Наши каналы:**

     [Антигембл](https://t.me/antigambl) — …

     [Блог «Лудочат»](https://t.me/LudoBlog) — …

     **Наши боты:**

     [Выручка](https://t.me/viruchkaa_bot?start=0012) — …

     [Алгоритм](https://t.me/algorithmga_bot?start=0011) — …
     ```

4. **Админские команды**  
   - `/sell_account` — отправляет ответ в чат или личку и удаляет вопрос+ответ через 2 минуты.  
   - `/quit_gambling` — оставляет ответ без удаления.  
   - Доступны только админам/creator’ам чата.

5. **SQLite**  
   - `data.db` хранит таблицу `users` (telegram_id, username, full_name, is_verified, invite_link).  
   - Реализована retry-логика при `sqlite3.OperationalError ("database is locked")`.  

---

## Обработка ошибок и edge-case

- **Повторный `/start verify_<ID>`**  
  Если заявка уже обработана или истекла, бот отправляет уведомление.

- **Обычный `/start`**  
  Бот предлагает нажать «Вступить» в публичном чате.

- **DM и логирование**  
  Если бот не может отправлять ЛС, публикует инструкции в публичный чат.  
  Если не может писать в канал `LOG_CHANNEL_ID`, сохраняет warning, продолжает работу.

- **Некорректная конфигурация**  
  Проверяется корректность полей `PRIVATE_DESTINATIONS`, `ADMIN_CHAT_IDS`, прерывает работу с ошибкой при invalid.

- **Invite link limit**  
  Ловится `TelegramForbiddenError`, логируется.  

- **SQLite corruption**  
  Ловятся любые ошибки `Exception` при сохранении, логируются, но бот продолжает работу без падения.

---

**Это финальная версия v10 с Markdown-ссылками.**  
