FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY config.example.yaml ./

ENV MONITOR_DB_PATH=/app/data/monitor.db

EXPOSE 8000

CMD ["uvicorn", "monitor.main:app", "--host", "0.0.0.0", "--port", "8000"]
