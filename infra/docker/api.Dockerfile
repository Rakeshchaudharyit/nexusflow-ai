FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY apps/api/requirements.lock ./
RUN pip install -r requirements.lock && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/knowledge && chown appuser:appuser /data/knowledge
COPY apps/api/app ./app
COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
COPY docs/demo-knowledge /app/demo-data/knowledge
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
