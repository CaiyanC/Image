"""Retrieve non-factual customer-service experience guidance.

The product evidence packet and this guidance channel are deliberately
separate. Experience cards may shape conversational structure, but they can
never prove a product fact, select a SKU, or replace a normal RAG lookup.
"""

from __future__ import annotations

import math
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


def _vector_score(row: dict[str, Any]) -> float | None:
    """Return a usable semantic score, rejecting lexical/fallback rows."""
    if str(row.get("_retrieval_signal") or "").strip().lower() != "vector":
        return None
    try:
        score = float(row.get("score"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return score


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
        min_score = float(
            getattr(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE", 0.50)
        )
    except (TypeError, ValueError):
        min_score = 0.50
    if not math.isfinite(min_score):
        min_score = 0.50
    min_score = max(-1.0, min(1.0, min_score))
    try:
        min_margin = float(
            getattr(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_MARGIN", 0.02)
        )
    except (TypeError, ValueError):
        min_margin = 0.02
    if not math.isfinite(min_margin):
        min_margin = 0.03
    min_margin = max(0.0, min(1.0, min_margin))
    try:
        retrieval_limit = max(max_cards * 4, 6)
        if normalized_skus:
            # Product-bound turns need both layers of experience guidance:
            # guidance written for the same SKU, when available, and global
            # communication guidance distilled from cross-product good/bad
            # cases.  The latter is deliberately limited to rows without a
            # SKU so an unrelated product's experience card cannot leak into
            # the turn.  This is retrieval scope, not a phrase or intent
            # router; product facts remain in the separate evidence packet.
            bound_rows = await knowledge_service.semantic_retrieve(
                db,
                query,
                sku=normalized_skus[0] if len(normalized_skus) == 1 else None,
                skus=normalized_skus if len(normalized_skus) > 1 else None,
                limit=retrieval_limit,
                source_types=[knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE],
                _include_retrieval_signal=True,
            )
            global_rows = await knowledge_service.semantic_retrieve(
                db,
                query,
                limit=max(retrieval_limit * 4, 24),
                source_types=[knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE],
                _include_retrieval_signal=True,
            )
            rows = [
                *bound_rows,
                *[
                    row for row in (global_rows or [])
                    if isinstance(row, dict)
                    and not str(row.get("sku") or "").strip()
                ],
            ]
        else:
            rows = await knowledge_service.semantic_retrieve(
                db,
                query,
                limit=retrieval_limit,
                source_types=[knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE],
                _include_retrieval_signal=True,
            )
    except Exception:
        # Experience is optional. Failure must leave the existing RAG path
        # untouched instead of replacing a factual answer with a fallback.
        return []

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    remaining_chars = max_chars
    ranked_rows: list[tuple[float, int, dict[str, Any]]] = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        score = _vector_score(row)
        if score is None or score < min_score:
            continue
        ranked_rows.append((score, index, row))

    # ``semantic_retrieve`` is a hybrid page: its final order deliberately
    # fuses vector and lexical ranks for general knowledge retrieval. This
    # optional channel needs the vector score itself, so rank only the rows
    # proven to be semantic and keep lexical fallback out of the packet.
    ranked_rows.sort(key=lambda item: (-item[0], item[1]))

    # Experience is a soft communication aid. If two approved cards are
    # semantically tied, omitting the aid is safer than injecting a weakly
    # differentiated topic (for example, cleaning guidance into a heat-source
    # question). This is a score-calibration boundary, not a phrase router;
    # the factual RAG path and the answer model remain unchanged.
    approved_ranked_rows = [
        item for item in ranked_rows
        if _approved_guidance_row(item[2])
    ]
    if (
        len(approved_ranked_rows) >= 2
        and approved_ranked_rows[0][0] - approved_ranked_rows[1][0] < min_margin
    ):
        return []

    for _score, _index, row in ranked_rows:
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
