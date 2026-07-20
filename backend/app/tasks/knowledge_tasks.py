from ..core.celery_app import celery_app
from ..services import knowledge_job_service


@celery_app.task(name="run_knowledge_job")
def run_knowledge_job(job_id: str) -> dict:
    return knowledge_job_service.run_job(job_id)
