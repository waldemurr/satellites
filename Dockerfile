FROM python:3.10-slim

# Установка зависимостей
WORKDIR /app

# Копирование файлов зависимостей
COPY requirements.txt .

# Установка зависимостей Python
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY . .

# Создание необходимых директорий
RUN mkdir -p /app/backend /app/data /app/module

# Копирование кода и данных
COPY backend/ /app/backend/
COPY data/ /app/data/
COPY module/ /app/module/

# Установка переменных окружения
ENV PYTHONPATH=/app

# Экспозиция порта
EXPOSE 5002

# Запуск приложения
CMD ["python", "/app/backend/run.py"]