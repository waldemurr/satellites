FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Бэкенд, расчётный модуль и данные
COPY backend/ /app/backend/
COPY data/ /app/data/

RUN mkdir -p /app/uploads

ENV PYTHONPATH=/app/backend

EXPOSE 5002

CMD ["python", "/app/backend/run.py"]
