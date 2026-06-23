# Production Deployment

This guide deploys the app on one Linux server for roughly 10-30 internal users.

## Prerequisites

- Linux server with 4+ CPU cores and 8 GB+ RAM recommended.
- Docker Engine 24+.
- Docker Compose plugin 2.20+.
- Ports 80 and 443 open to users.
- A domain name and TLS certificate if HTTPS is required.

Check versions:

```bash
docker --version
docker compose version
```

## First Deployment

1. Clone the repository:

```bash
git clone <repo-url> caiyan
cd caiyan
```

2. Create production environment:

```bash
cp .env.example .env
nano .env
```

Fill at least:

- `SECRET_KEY`
- `DEFAULT_ADMIN_PASSWORD`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `DATABASE_URL`
- `REDIS_URL`
- `DMXAPI_API_KEY` if image generation is enabled

For the provided compose file, use internal service names:

```env
DATABASE_URL=postgresql://user:password@db:5432/caiyan
REDIS_URL=redis://redis:6379/0
```

3. Build and start services:

```bash
docker compose up -d --build
```

4. Run database migrations:

```bash
docker compose exec backend python -m alembic upgrade head
```

5. Check service health:

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 worker
docker compose logs --tail=100 frontend
```

6. Open the site:

```text
http://<server-ip>/
```

## Logs

All services:

```bash
docker compose logs -f
```

Single service:

```bash
docker compose logs -f backend
docker compose logs -f worker
docker compose logs -f redis
docker compose logs -f db
docker compose logs -f frontend
```

## Restart A Single Service

```bash
docker compose restart backend
docker compose restart worker
docker compose restart frontend
```

Rebuild one service after code changes:

```bash
docker compose up -d --build backend
docker compose up -d --build worker
docker compose up -d --build frontend
```

## Scale Workers

For larger upload bursts, increase worker processes:

```bash
docker compose up -d --scale worker=2
```

Tune per-worker concurrency in `.env`:

```env
CELERY_CONCURRENCY=4
```

For a 4-core server, start with one worker service and `CELERY_CONCURRENCY=4`. Increase gradually while watching CPU, memory, PostgreSQL connections, and Redis latency.

## Verify Concurrent Upload Stability

1. Confirm services are healthy:

```bash
docker compose ps
docker compose exec redis redis-cli ping
docker compose exec backend python -m alembic current
```

2. Log in as an admin user.
3. Ask 10 users to upload small PDF/TXT files at the same time, or run the existing upload regression script from a trusted machine.
4. Watch task movement:

```bash
docker compose logs -f worker
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select status, count(*) from knowledge_parse_tasks group by status;"
```

Expected result:

- API responses return `task_id` quickly.
- Worker logs show `parse_document` tasks.
- `knowledge_parse_tasks.status` moves from `pending/processing` to `done` or `error`.
- Duplicate uploads reuse existing documents/tasks instead of creating duplicate chunks.

## Common Issues

### Redis connection failed

Check Redis health:

```bash
docker compose ps redis
docker compose logs --tail=100 redis
docker compose exec redis redis-cli ping
```

Check `.env`:

```env
REDIS_URL=redis://redis:6379/0
```

Restart worker after changing Redis settings:

```bash
docker compose restart worker backend
```

### Database migration failed

Check database is healthy:

```bash
docker compose ps db
docker compose logs --tail=100 db
```

Run the duplicate precheck before applying stability constraints:

```bash
docker compose exec backend python scripts/check_knowledge_duplicates.py
```

Then rerun:

```bash
docker compose exec backend python -m alembic upgrade head
```

If duplicates are reported, back up the database and resolve them manually before retrying.

### Frontend 404 after refresh

The Nginx config must route SPA paths to `index.html`:

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

Rebuild and restart frontend:

```bash
docker compose up -d --build frontend
```

### Uploads fail or worker cannot read files

Backend and worker must share the same `backend_uploads` volume:

```bash
docker compose inspect backend_uploads
docker compose restart backend worker
```
