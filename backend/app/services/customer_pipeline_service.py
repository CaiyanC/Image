"""Runtime selection for customer-service pipelines.

Pipeline selection is an operational deployment switch, not a customer
question router.  The legacy path remains the safe default until the isolated
semantic RAG path has been accepted in the development environment.
"""

from ..core.config import settings


LEGACY_PIPELINE = "legacy"
SEMANTIC_RAG_V2_PIPELINE = "semantic_rag_v2"
SUPPORTED_PIPELINES = frozenset({LEGACY_PIPELINE, SEMANTIC_RAG_V2_PIPELINE})
PIPELINE_HEADER = "X-Customer-Service-Pipeline"


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def configured_customer_service_pipeline() -> str:
    value = _normalize(getattr(settings, "CUSTOMER_SERVICE_PIPELINE", ""))
    return value if value in SUPPORTED_PIPELINES else LEGACY_PIPELINE


def resolve_customer_service_pipeline(requested: str | None = None) -> str:
    """Resolve the process default with a development-only request override.

    A production request can never select a different pipeline through a
    public header.  Production rollback is therefore an environment/config
    operation, while dev can opt into v2 for controlled HTTP comparison.
    """
    configured = configured_customer_service_pipeline()
    requested_value = _normalize(requested)
    if requested_value not in SUPPORTED_PIPELINES:
        return configured
    if str(getattr(settings, "APP_ENV", "")).strip().lower() == "prod":
        return configured
    if not bool(getattr(settings, "CUSTOMER_SERVICE_PIPELINE_OVERRIDE_ENABLED", False)):
        return configured
    return requested_value


def is_semantic_rag_v2(pipeline: str | None) -> bool:
    return _normalize(pipeline) == SEMANTIC_RAG_V2_PIPELINE
