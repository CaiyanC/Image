# Celery Worker

Knowledge file parsing uses Redis + Celery. The API process saves the file, creates a `knowledge_parse_tasks` row, and enqueues `parse_document`. A separate worker process runs the parser.

## Current Standard

Use the environment-specific scripts from the repository root. Do not start a generic Celery worker without queue, worker name, pidfile, and logfile.

| Environment | Script | Redis | Queue | Worker name | Pidfile | Logfile |
| --- | --- | --- | --- | --- | --- | --- |
| prod | `start-prod.bat` | `redis://localhost:6379/0` | `celery_prod` | `worker_prod@<COMPUTERNAME>` | `logs\prod\celery.pid` | `logs\prod\celery.log` |
| dev | `start-dev.bat` | `redis://localhost:6379/1` | `celery_dev` | `worker_dev@<COMPUTERNAME>` | `logs\dev\celery.pid` | `logs\dev\celery.log` |

The old default queue `celery` is not used by this project anymore.

## Start Redis Locally

The scripts manage the shared Docker Redis container `caiyan-redis`:

```powershell
docker run --name caiyan-redis -p 6379:6379 -d redis:7
```

Prod and dev are separated by Redis DB index:

- prod: `redis://localhost:6379/0`
- dev: `redis://localhost:6379/1`

## Manual Worker Commands

Prefer the scripts. If a manual command is needed for diagnosis, load the matching env first and keep the queue/name/pid/log arguments.

Prod:

```powershell
cd backend
.\venv\Scripts\activate
python -m celery -A app.core.celery_app.celery_app worker --loglevel=info --pool=solo -Q celery_prod -n worker_prod@%COMPUTERNAME% --pidfile=..\logs\prod\celery.pid --logfile=..\logs\prod\celery.log
```

Dev:

```powershell
cd backend
.\venv\Scripts\activate
python -m celery -A app.core.celery_app.celery_app worker --loglevel=info --pool=solo -Q celery_dev -n worker_dev@%COMPUTERNAME% --pidfile=..\logs\dev\celery.pid --logfile=..\logs\dev\celery.log
```

Do not use the legacy command:

```powershell
celery -A app.core.celery_app.celery_app worker --loglevel=info --pool=solo
```

It binds to the default queue and can mix prod/dev tasks.

## Stop Workers

Use the matching stopper:

```bat
stop-prod.bat
stop-dev.bat
```

Do not kill all Celery or all Python processes. The stop scripts target pidfile, worker name, queue name, and fixed environment ports.

## Verify The Worker

1. Start the matching API service and worker through `start-prod.bat` or `start-dev.bat`.
2. Upload a knowledge file.
3. Confirm the API response includes `task_id`.
4. Watch the matching worker log for a `parse_document` task.
5. Poll the matching API:

```powershell
curl http://localhost:8001/api/knowledge-base/tasks/<task_id> -H "Authorization: Bearer <token>"
```

The status should move from `pending` or `processing` to `done` or `error`.
