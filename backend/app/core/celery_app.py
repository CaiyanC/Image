from celery import Celery

from .config import settings


celery_app = Celery(
    "caiyan_backend",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.parse_tasks"],
)

celery_app.conf.update(
    task_default_queue=settings.CELERY_QUEUE,
    task_track_started=True,
    timezone="UTC",
)
