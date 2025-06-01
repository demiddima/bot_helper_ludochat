FROM python:3.11-slim

WORKDIR /app

# Устанавливаем необходимые системные пакеты для сборки aiomysql
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         build-essential \
         default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
