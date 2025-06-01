# 1) Базовый образ: берем python:3.11.9-slim
FROM python:3.11.9

# 2) Создаём папку /app внутри контейнера и делаем её рабочей
WORKDIR /app

# 3) Копируем указанный requirements.txt в контейнер
COPY requirements.txt .

# 4) Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# 5) Копируем весь код проекта (кроме того, что указано в .dockerignore)
COPY . .

# 6) Команда запуска: просто запускаем main.py
CMD ["python", "main.py"]