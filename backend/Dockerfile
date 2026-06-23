FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_MODE=api
ENV WORKERS=4
ENV CELERY_CONCURRENCY=4
ENV CELERY_QUEUE=celery_prod
ENV CELERY_WORKER_NAME=worker_prod

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "if [ \"$APP_MODE\" = \"worker\" ]; then celery -A app.core.celery_app.celery_app worker --loglevel=info --pool=prefork --concurrency=${CELERY_CONCURRENCY:-4} -Q ${CELERY_QUEUE} -n ${CELERY_WORKER_NAME}@%h; else gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WORKERS:-4} -b 0.0.0.0:8000 --timeout 300; fi"]
