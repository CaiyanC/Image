"""Runtime selection for customer-service pipelines.

Pipeline selection is an operational deployment switch, not a customer
question router.  Development defaults to the established semantic-RAG
baseline; production keeps its configured value until an explicit release.
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
    value = _normalize(getattr(settings, "CUSTOMER_SERVICE_PIPELINE", ""))
    if value in SUPPORTED_PIPELINES:
        return value
    # Keep an invalid or missing setting from silently putting the development
    # UI back on the legacy route.  Production remains fail-closed to legacy
    # until its deployment configuration is explicitly changed.
    if str(getattr(settings, "APP_ENV", "")).strip().lower() == "dev":
        return SEMANTIC_RAG_V2_PIPELINE
    return LEGACY_PIPELINE


def resolve_customer_service_pipeline(
    requested: str | None = None,
    *,
    server_selected: bool = False,
) -> str:
    """Resolve the process default with a controlled runtime selection.

    A production request can never select a different pipeline through a
    public header.  A dedicated server-owned endpoint may select one known
    pipeline explicitly; this supports a production side-by-side entry while
    preserving the configured default and its rollback path.
    """
    configured = configured_customer_service_pipeline()
    requested_value = _normalize(requested)
    if requested_value not in SUPPORTED_PIPELINES:
        return configured
    if server_selected:
        return requested_value
    if str(getattr(settings, "APP_ENV", "")).strip().lower() == "prod":
        return configured
    if not bool(getattr(settings, "CUSTOMER_SERVICE_PIPELINE_OVERRIDE_ENABLED", False)):
        return configured
    return requested_value


def is_semantic_rag_v2(pipeline: str | None) -> bool:
    return _normalize(pipeline) == SEMANTIC_RAG_V2_PIPELINE


def is_workbuddy_rag(pipeline: str | None) -> bool:
    return _normalize(pipeline) == WORKBUDDY_RAG_PIPELINE


def is_workbuddy_agent(pipeline: str | None) -> bool:
    return _normalize(pipeline) == WORKBUDDY_AGENT_PIPELINE
