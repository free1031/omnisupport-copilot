FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/copilot_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/copilot_api/app/ ./app/
COPY observability/ ./observability/

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
