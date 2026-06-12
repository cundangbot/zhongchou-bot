FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import importlib; importlib.import_module('app.main')"
CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]
