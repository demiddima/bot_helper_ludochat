FROM python:3.11-slim

WORKDIR /app

# Устанавливаем базовые системные пакеты для C-компиляции + dev-библиотеки
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         build-essential \
         default-libmysqlclient-dev \
         libssl-dev \
         libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# При желании можно обновить pip, чтобы он схватил самые свежие колёсы
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "main.py"]
