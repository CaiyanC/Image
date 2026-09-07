"""Runtime selection for customer-service pipelines.

Pipeline selection is an operational deployment switch, not a customer
question router. Production exposes one RAG chain; development retains
explicit comparison overrides. This takes effect on the next code release.
"""

from ..core.config import settings


LEGACY_PIPELINE = "legacy"
SEMANTIC_RAG_V2_PIPELINE = "semantic_rag_v2"
WORKBUDDY_RAG_PIPELINE = "workbuddy_rag_v1"
WORKBUDDY_AGENT_PIPELINE = "workbuddy_agent_v2"
SUPPORTED_PIPELINES = frozenset({
    LEGACY_PIPELINE,
    SEMANTIC_RAG_V2_PIPELINE,
    WORKBUDDY_RAG_PIPELINE,
    WORKBUDDY_AGENT_PIPELINE,
})
PIPELINE_HEADER = "X-Customer-Service-Pipeline"


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def configured_customer_service_pipeline() -> str:
    if str(getattr(settings, "APP_ENV", "")).strip().lower() == "prod":
        return WORKBUDDY_RAG_PIPELINE
    value = _normalize(getattr(settings, "CUSTOMER_SERVICE_PIPELINE", ""))
    if value in SUPPORTED_PIPELINES:
        return value
    # Keep an invalid or missing setting from silently putting the development
    # UI back on the legacy route. Production is locked to RAG above.
    if str(getattr(settings, "APP_ENV", "")).strip().lower() == "dev":
        return SEMANTIC_RAG_V2_PIPELINE
    return LEGACY_PIPELINE


def resolve_customer_service_pipeline(
    requested: str | None = None,
    *,
    server_selected: bool = False,
) -> str:
    """Resolve the process default with a controlled runtime selection.

    Production always uses the single RAG pipeline, including server-selected
    requests. Development keeps controlled overrides for comparison tests.
    """
    configured = configured_customer_service_pipeline()
    requested_value = _normalize(requested)
    if requested_value not in SUPPORTED_PIPELINES:
        return configured
    if str(getattr(settings, "APP_ENV", "")).strip().lower() == "prod":
        return configured
    if server_selected:
        return requested_value
    if not bool(getattr(settings, "CUSTOMER_SERVICE_PIPELINE_OVERRIDE_ENABLED", False)):
        return configured
    return requested_value


def is_semantic_rag_v2(pipeline: str | None) -> bool:
    return _normalize(pipeline) == SEMANTIC_RAG_V2_PIPELINE


def is_workbuddy_rag(pipeline: str | None) -> bool:
    return _normalize(pipeline) == WORKBUDDY_RAG_PIPELINE


def is_workbuddy_agent(pipeline: str | None) -> bool:
    return _normalize(pipeline) == WORKBUDDY_AGENT_PIPELINE
