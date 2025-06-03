# Бот-помощник «LudoChat» v11

**Версия v11 адаптирована под новую архитектуру хранения данных:**
- Используем MySQL и две ключевые таблицы:
  1. **chats** — список каналов и чатов, где бот является администратором.
  2. **user_memberships** — факт текущего членства пользователя (telegram_id ⇄ chat_id).

---

## 1. Структура проекта

```
bot_helper_ludochat/
├── README.md
├── requirements.txt
├── config.py
├── storage.py
├── main.py
├── set_admin_commands.py    (опционально)
└── handlers/
    ├── join.py
    └── commands.py          (если нужны дополнительные команды)
```

- **README.md** — текущий файл с описанием новой архитектуры.
- **requirements.txt** — список зависимостей (aiogram, aiomysql и пр.).
- **config.py** — конфигурация (токен бота, ID чатов, MySQL-параметры и т. д.).
- **storage.py** — функции для работы с MySQL (инициализация пула, создание таблиц, `upsert_chat`, `delete_chat`, `add_user_to_chat`, `remove_user_from_chat`).
- **main.py** — точка входа: инициализация БД, регистрация роутеров, запуск поллинга.
- **handlers/join.py** — обработчики:
  - входящие заявки (ChatJoinRequest) → отправка Условий/кнопки,
  - `/start verify_<user_id>` → одобрение и добавление пользователя в `user_memberships`,
  - `@router.my_chat_member()` → автоматическое обновление таблицы `chats`,
  - `@router.chat_member()` → обновление `user_memberships` при изменении статуса участника.
- **handlers/commands.py** — (опционально) админские команды (если нужны дополнительные).

---

## 2. Настройка

1. Создайте (или откройте) файл **config.py** и задайте в нём обязательные поля:

   ```python
   # TOKEN вашего бота
   BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ"

   # ID публичного чата, куда приходят заявки (через кнопку «Вступить»)
   PUBLIC_CHAT_ID = -1001234567890

   # ID канала/чата для отправки логов об ошибках
   ERROR_LOG_CHANNEL_ID = -1009876543210

   # Список приватных чатов, куда бот будет генерировать invite-ссылки
   PRIVATE_DESTINATIONS = [
       {
           "title": "12 шагов",
           "chat_id": -1001111111111,
           "description": "Чат программы «12 шагов»"
       },
       {
           "title": "Поп-психология",
           "chat_id": -1002222222222,
           "description": "Обсуждение психологических методов"
       },
       # и т. д.
   ]

   # MySQL-параметры
   DB_HOST = "localhost"
   DB_PORT = 3306
   DB_USER = "bot_user"
   DB_PASSWORD = "bot_password"
   DB_NAME = "ludochat_db"

   # (Опционально) список чатов, где ставить админские команды (если используете set_admin_commands.py)
   ADMIN_CHAT_IDS = [
       -1003333333333,
       -1004444444444,
   ]
   ```

2. **Установите зависимости**:
   ```bash
   pip install -r requirements.txt
   ```
   В `requirements.txt` должны быть примерно:
   ```
   aiogram==3.x
   aiomysql==0.x
   ```

3. **Создайте базу MySQL** (если ещё не создана) и дайте пользователю-боту все права:
   ```sql
   CREATE DATABASE ludochat_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'bot_user'@'localhost' IDENTIFIED BY 'bot_password';
   GRANT ALL PRIVILEGES ON ludochat_db.* TO 'bot_user'@'localhost';
   FLUSH PRIVILEGES;
   ```

4. **Запустите бота**:
   ```bash
   python main.py
   ```
   При старте бот автоматически создаст нужные таблицы в MySQL:
   - `chats`
   - `user_memberships`

5. **(Опционально) Обновление админских команд**:
   Если вы используете файл `set_admin_commands.py` для установки slash-команд, запустите:
   ```bash
   python set_admin_commands.py
   ```

---

## 3. Схема базы данных

### 3.1 Таблица `chats`

Хранит информацию обо всех чатах/каналах, где бот является администратором.

```sql
CREATE TABLE IF NOT EXISTS chats (
    id BIGINT PRIMARY KEY,              -- telegram_id чата/канала
    title VARCHAR(256) NOT NULL,        -- заголовок (chat.title)
    type ENUM('public_channel','supergroup','group','private_channel') NOT NULL,
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

- **`id`** — уникальный ID чата/канала.
- **`title`** — название, которое Telegram отдаёт в `chat.title`.
- **`type`** — тип (public_channel, supergroup, group или private_channel).
- **`added_at`** — автоматически сохраняется время создания/обновления записи.

### 3.2 Таблица `user_memberships`

Хранит факт текущего членства пользователя (telegram_id) в конкретном чате из `chats`.

```sql
CREATE TABLE IF NOT EXISTS user_memberships (
    user_id BIGINT NOT NULL,           -- telegram_id пользователя
    chat_id BIGINT NOT NULL,           -- ID чата/канала (внешний ключ → chats.id)
    joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, chat_id),
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

- **`user_id`** — telegram_id участника.
- **`chat_id`** — чат/канал из таблицы `chats`.
- **`joined_at`** — время последнего добавления (входит в чат).
- Внешний ключ на `chats(id)` гарантирует, что chat_id всегда валиден. Если чат удалён из `chats`, все соответствующие записи о членстве будут автоматически удалены (ON DELETE CASCADE).

---

## 4. Как работает бот

### 4.1 Startup / инициализация

1. **`main.py`** вызывает:
   ```python
   await init_db_pool()
   ```
   — это создаёт пул MySQL-подключений и автоматически создаёт таблицы `chats` и `user_memberships`, если их ещё нет.

2. Регистрируются роутеры из папки `handlers/` (в первую очередь `join.py`).

3. Запускается длинный поллинг (или webhook).

---

### 4.2 Обработка ChatJoinRequest → «Условия»

1. Пользователь нажимает кнопку **«Вступить»** в **публичном** чате (`PUBLIC_CHAT_ID`).
2. Telegram отправляет апдейт `ChatJoinRequest` (объект `update: ChatJoinRequest`), который ловит хендлер:
   ```python
   @router.chat_join_request(F.chat.id == PUBLIC_CHAT_ID)
   async def handle_join(update: ChatJoinRequest):
       user = update.from_user
       join_requests[user.id] = update

       bot_username = (await bot.get_me()).username
       payload = f"verify_{user.id}"
       url = f"https://t.me/{bot_username}?start={payload}"

       kb = InlineKeyboardMarkup(
           inline_keyboard=[[InlineKeyboardButton(text="✅ Я согласен", url=url)]]
       )

       await bot.send_message(user.id, TERMS_MESSAGE, reply_markup=kb, parse_mode="HTML")
   ```
3. В `join_requests` сохраняется pending-запрос, а пользователю в ЛС отправляется сообщение с условиями и кнопкой «✅ Я согласен» (ссылка открывает бота с командой `/start verify_<user_id>`).

---

### 4.3 Обработка `/start verify_<user_id>`

1. Пользователь кликает на кнопку, Telegram открывает приватный чат с ботом и шлёт команду:
   ```
   /start verify_<USER_ID>
   ```
2. Хендлер `process_start`:
   ```python
   @router.message(F.text.startswith("/start"))
   async def process_start(message: Message):
       parts = message.text.split()
       if len(parts) == 2 and parts[1].startswith("verify_"):
           uid = int(parts[1].split("_", 1)[1])

           if message.from_user.id == uid and uid in join_requests:
               join_requests.pop(uid)

               await bot.approve_chat_join_request(PUBLIC_CHAT_ID, uid)
               logging.info(f"[APPROVE] Заявка {uid} одобрена")

               # ── Главное изменение: сначала помещаем PUBLIC_CHAT_ID в таблицу chats
               chat_obj = await bot.get_chat(PUBLIC_CHAT_ID)
               await upsert_chat(chat_obj.id, chat_obj.title or "", chat_obj.type)

               # ── Затем фиксируем факт членства пользователя в PUBLIC_CHAT_ID
               await add_user_to_chat(uid, PUBLIC_CHAT_ID)

               # ── Наконец, отправляем приватные ссылки
               await send_links_message(uid)
           else:
               await message.reply("❗ Некорректный запрос верификации")
       else:
           await message.reply("Привет! Чтобы верифицироваться, нажмите «Вступить» в публичном чате.")
   ```
3. **Что происходит:**
   - Проверяем, что `uid` действительно есть в `join_requests` (то есть это тот же пользователь).
   - Одобряем его заявку в публичном чате (`approve_chat_join_request`).
   - Через `bot.get_chat(PUBLIC_CHAT_ID)` получаем информацию о чате и вызываем `upsert_chat(...)`: если таблица `chats` не содержит этой записи, она создаётся; если уже есть, обновляется заголовок.
   - Сразу после этого фиксируем факт, что этот пользователь входит в этот чат: `add_user_to_chat(uid, PUBLIC_CHAT_ID)`. Результат — в `user_memberships` появится запись `(uid, PUBLIC_CHAT_ID, joined_at)`.
   - Отправляем пользователю второе сообщение с приватными invite-ссылками (функция `send_links_message(uid)`).

---

### 4.4 Обработчики ChatMemberUpdated (для «чистой» синхронизации)

#### 4.4.1 `@router.my_chat_member()` — статус **бота**

```python
@router.my_chat_member()
async def on_bot_status_change(event: ChatMemberUpdated):
    updated = event.new_chat_member.user
    bot_info = await bot.get_me()
    if updated.id != bot_info.id:
        return

    new_status = event.new_chat_member.status
    chat = event.chat

    # Если бот стал админом или создателем → сохраняем чат в таблицу chats
    if new_status in ("administrator", "creator"):
        await upsert_chat(chat.id, chat.title or "", chat.type)

    # Если бот вышел или был кикнут → удаляем чат из таблицы chats
    elif new_status in ("left", "kicked"):
        await delete_chat(chat.id)
```

- **Когда бот добавлен** (или получил права администратора) → появляется запись в `chats`.
- **Когда бот удалён** (или лишён прав) → запись об этом чате удаляется из `chats`, и каскадом удаляются все `user_memberships` для этого `chat_id`.

#### 4.4.2 `@router.chat_member()` — статус **пользователей**

```python
@router.chat_member()
async def on_user_status_change(event: ChatMemberUpdated):
    updated_user = event.new_chat_member.user
    bot_info = await bot.get_me()
    if updated_user.id == bot_info.id:
        return  # игнорируем события, связанные с самим ботом

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    chat_id = event.chat.id

    # Если пользователь был вне чата/кикнут, а стал member → добавляем в user_memberships
    if old_status in ("left", "kicked") and new_status == "member":
        await add_user_to_chat(updated_user.id, chat_id)

    # Если пользователь вышел или был кикнут → удаляем из user_memberships
    elif new_status in ("left", "kicked"):
        await remove_user_from_chat(updated_user.id, chat_id)
```

- **Когда новый пользователь** (`new_status == "member"`) входит в чат, мы фиксируем его в `user_memberships` (через `add_user_to_chat`).
- **Когда пользователь** (`new_status in ("left","kicked")`) выходит из чата → удаляем запись через `remove_user_from_chat`.

---

## 5. Админские команды (опционально)

Если вам нужны собственные slash-команды, создайте файл **set_admin_commands.py** (пример):

```python
import asyncio
from aiogram import Bot

from config import BOT_TOKEN, ADMIN_CHAT_IDS

async def set_commands():
    bot = Bot(token=BOT_TOKEN)
    for chat_id in ADMIN_CHAT_IDS:
        await bot.set_chat_commands(
            commands=[
                ("sell_account", "Продать аккаунт"),
                ("quit_gambling", "Прекратить играть")
            ],
            scope={"type": "chat", "chat_id": chat_id}
        )
        print(f"Команды установлены в чате {chat_id}")
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(set_commands())
```

Запуск:
```bash
python set_admin_commands.py
```

После этого в указанных чатах будут команды `/sell_account` и `/quit_gambling`.

---

## 6. Пример работы

1. **Старт бота**:
   ```
   python main.py
   ```
   → В логах вы увидите:
   ```
   [DB] Таблица chats создана/проверена
   [DB] Таблица user_memberships создана/проверена
   ```

2. **Добавляем бота** в публичный чат (PUBLIC_CHAT_ID) с правами администратора → появляется запись в таблице `chats`:
   ```sql
   SELECT * FROM chats;
   -- Результат:
   -- | id           | title            | type             | added_at           |
   -- | -1001234567890 | «ЛудоПаблик»     | supergroup       | 2025-06-04 10:22:13 |
   ```

3. **Пользователь А** нажимает «Вступить» в этом публичном чате → видит условия и кнопку «✅ Я согласен».

4. **Пользователь А** кликает кнопку → `/start verify_<USER_A_ID>` в личном чате → бот:
   - Одобряет заявку (approve_chat_join_request).
   - Делает `upsert_chat(...)` (на случай, если ранее чат не был в `chats`).
   - Делает `add_user_to_chat(USER_A_ID, PUBLIC_CHAT_ID)`.
   - Отправляет приватные invite-ссылки.

5. **Проверяем**:
   ```sql
   SELECT * FROM user_memberships;
   -- Результат:
   -- | user_id     | chat_id         | joined_at           |
   -- | 123456789   | -1001234567890  | 2025-06-04 10:24:01 |
   ```

6. **Пользователь А** выходит из публичного чата → хендлер `@router.chat_member()` срабатывает:
   - `remove_user_from_chat(USER_A_ID, PUBLIC_CHAT_ID)`.
   - В таблице `user_memberships` строка исчезает.

---

## 7. Частые вопросы и рекомендации

1. **Почему нет таблицы `users`?**  
   Мы упростили архитектуру: больше не храним отдельную таблицу профилей. Факт верификации отражается наличием строки `(user_id, PUBLIC_CHAT_ID)` в `user_memberships`. Если пользователь выходит из публичного чата, его запись удаляется.

2. **Как узнать, в каких чатах сейчас конкретный пользователь?**  
   ```sql
   SELECT chat_id FROM user_memberships WHERE user_id = <USER_ID>;
   ```
   Это вернёт список всех `chat_id`, где он сейчас состоит.

3. **Как получить список всех пользователей в конкретном чате?**  
   ```sql
   SELECT user_id FROM user_memberships WHERE chat_id = <CHAT_ID>;
   ```

4. **Что происходит, если бот удаляется из какого-либо чата?**  
   В `on_bot_status_change` ловится событие `new_status in ("left","kicked")` → `delete_chat(chat_id)`.  
   SQL-касCADE гарантирует, что все связанные записи в `user_memberships` для этого `chat_id` будут удалены автоматически.

5. **Если бот не успел поймать `my_chat_member` для какого-то чата, но пользователь прошёл верификацию напрямую?**  
   В `process_start` перед `add_user_to_chat(...)` выполняется `upsert_chat(...) via bot.get_chat(PUBLIC_CHAT_ID)`, поэтому публичный чат гарантированно добавится в `chats`.

6. **Поддержка больших каналов**  
   Bot API не даёт «список всех участников» напрямую. Если вам нужно однажды синхронизировать всех текущих подписчиков, используйте отдельный скрипт на Telethon или Pyrogram (userbot), который делает `get_participants()` и заполняет `user_memberships`.

---

## 8. Завершение

С новой архитектурой:
- **Лаконичный SQL** — две таблицы, полностью покрывающие задачу «где и кто сейчас состоит».
- **Экономия ресурсов** — нет лишних таблиц с историей; храним только актуальное состояние.
- **Простая масштабируемость** — при добавлении новых приватных чатов достаточно добавить их в `PRIVATE_DESTINATIONS` и бот автоматически начнёт выдавать ссылки, а хендлеры будут синхронизировать статус.

> Удачного использования!  
> Если потребуются доработки или возникнут вопросы — пишите.
