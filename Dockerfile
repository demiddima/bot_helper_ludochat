# ┌─────────────────────────────────────────────────────────────────┐
# │            Dockerfile для bot_helper_ludochat (ENV-only)       │
# └─────────────────────────────────────────────────────────────────┘

# 1) Базовый образ с Python 3.11 (slim)
FROM python:3.11-slim

# 2) Переключаемся в рабочую директорию /app
WORKDIR /app

# 3) Устанавливаем все нужные «dev»-библиотеки для сборки C-расширений:
#    - build-essential            (для gcc, make и т. п.)
#    - default-libmysqlclient-dev (mysql_config + заголовки MySQL)
#    - libssl-dev                 (заголовки OpenSSL)
#    - libffi-dev                 (заголовки libffi)
#    - python3-dev                (заголовок Python.h)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         build-essential \
         default-libmysqlclient-dev \
         libssl-dev \
         libffi-dev \
         python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 4) Копируем файл зависимостей и устанавливаем Python-библиотеки
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 5) Копируем весь исходный код приложения
#    (в том числе config.py, main.py, папки handlers/ и services/)
COPY . .
EXPOSE 8080
# 6) По умолчанию выполняем команду запуска бота:
#    «-u» отключает буферизацию stdout/stderr, чтобы логи сразу шли в консоль
CMD ["python", "-u", "main.py"]
