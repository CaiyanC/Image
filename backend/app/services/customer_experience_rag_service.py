"""Retrieve non-factual customer-service experience guidance.

The product evidence packet and this guidance channel are deliberately
separate. Experience cards may shape conversational structure, but they can
never prove a product fact, select a SKU, or replace a normal RAG lookup.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..core.config import settings
from . import knowledge_service


_APPROVED_REVIEW_STATUS = "approved_pilot"
_AUTHORITY_LEVEL = "candidate_only"


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)].rstrip() + "…"


def _normalized_skus(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(
        str(value or "").strip().upper()
        for value in (values or [])
        if str(value or "").strip()
    ))[:12]


def _approved_guidance_row(row: dict[str, Any]) -> bool:
    if str(row.get("source_type") or "").strip() != knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE:
        return False
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return (
        metadata.get("fact_authority") is False
        and str(metadata.get("authority_level") or "").strip() == _AUTHORITY_LEVEL
        and str(metadata.get("review_status") or "").strip() == _APPROVED_REVIEW_STATUS
        and str(metadata.get("production_use") or "").strip() == "experience_guidance_only"
    )


async def retrieve_experience_guidance(
    db: Session,
    *,
    question: str,
    skus: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return a tiny, audited strategy packet without adding an LLM call."""
    if not bool(getattr(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", False)):
        return []
    query = str(question or "").strip()
    if not query:
        return []

    normalized_skus = _normalized_skus(skus)
    max_cards = max(
        1,
        min(int(getattr(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", 2)), 3),
    )
    max_chars = max(
        300,
        min(int(getattr(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CHARS", 1200)), 1800),
    )
    try:
        rows = await knowledge_service.semantic_retrieve(
            db,
            query,
            sku=normalized_skus[0] if len(normalized_skus) == 1 else None,
            skus=normalized_skus if len(normalized_skus) > 1 else None,
            limit=max(max_cards * 4, 6),
            source_types=[knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE],
        )
    except Exception:
        # Experience is optional. Failure must leave the existing RAG path
        # untouched instead of replacing a factual answer with a fallback.
        return []

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    remaining_chars = max_chars
    for row in rows or []:
        if not isinstance(row, dict) or not _approved_guidance_row(row):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        guidance_id = str(metadata.get("source_id") or row.get("source_id") or "").strip()
        content = str(row.get("content") or "").strip()
        identity = guidance_id or content
        if not identity or identity in seen or not content or remaining_chars <= 0:
            continue
        seen.add(identity)
        clipped = _clip_text(content, remaining_chars)
        result.append({
            "guidance_id": guidance_id or None,
            "sku": str(row.get("sku") or "").strip().upper() or None,
            "intent": str(metadata.get("intent") or "").strip() or None,
            "guidance": clipped,
            "authority_level": _AUTHORITY_LEVEL,
            "fact_authority": False,
        })
        remaining_chars -= len(clipped)
        if len(result) >= max_cards:
            break
    return result


def guidance_ids(rows: list[dict[str, Any]] | None) -> list[str]:
    return [
        str(row.get("guidance_id") or "").strip()
        for row in (rows or [])
        if isinstance(row, dict) and str(row.get("guidance_id") or "").strip()
    ]
