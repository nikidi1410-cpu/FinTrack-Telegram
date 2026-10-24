FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Jakarta

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN useradd --create-home appuser \
    && mkdir -p logs credentials \
    && chown -R appuser /app
USER appuser

EXPOSE 8000

# Service account JSON di-mount saat runtime, mis:
#   docker run --env-file .env -v ./credentials:/app/credentials:ro -p 8000:8000 fintrack-wa
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
