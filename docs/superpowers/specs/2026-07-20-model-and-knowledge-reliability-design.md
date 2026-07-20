# Model and Knowledge Reliability Design

## Scope

This change makes model selection deterministic, protects configured API keys at rest, and moves product-reindex and embedding-retry jobs from the API process into Celery.

## Decisions

- Each model configuration has an explicit per-type default. The backend deterministically falls back to the lexicographically first enabled model only when none is marked default.
- Model keys are encrypted with a Fernet key derived from `MODEL_CONFIG_ENCRYPTION_KEY`, or from `SECRET_KEY` as a compatibility fallback. Responses expose only `api_key_configured`; blank submitted keys preserve an existing encrypted key.
- The built-in DMXAPI environment key is used only as a fallback for built-in DMXAPI image models, never for a user-defined provider.
- Embedding remains environment-managed by `DASHSCOPE_API_KEY` and is read-only in the admin UI.
- Knowledge jobs persist in a database table and are dispatched by a Celery task. API processes only create and read job records.
- Video generation remains unavailable and is hidden in the UI; its API returns HTTP 501.

## Release

Development deployment needs one backend and Celery worker restart. Production requires the same migration/restart only after explicit publication approval.
