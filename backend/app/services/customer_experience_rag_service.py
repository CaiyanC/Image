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


_APPROVED_REVIEW_STATUSES = {"approved_pilot", "auto_generated_pilot"}
_AUTHORITY_LEVEL = "candidate_only"
_STRATEGY_QUERY_MARKERS = (
    "犹豫", "纠结", "值得买", "值不值得", "性价比", "价格高", "太贵", "贵不贵",
    "推荐", "怎么选", "选哪", "帮我选", "帮我挑", "适合我", "购买前", "为什么买",
    "卖点", "亮点", "怎么介绍", "客服", "如何承接", "顾虑", "担心", "不满意",
    "差评", "退换", "下单", "想买", "买这款", "怎么样",
)
_FACT_QUERY_MARKERS = (
    "容量", "重量", "尺寸", "材质", "热源", "炉具", "燃料", "兼容", "适配",
    "配件", "包含", "承重", "清洁", "清洗", "怎么用", "使用方法", "保修", "发货", "物流",
)
_DIRECT_FACT_QUERY_MARKERS = (
    "\u5ba4\u5185", "\u5361\u5f0f\u7089", "\u71c3\u6c14\u7089", "\u660e\u706b", "\u9152\u7cbe\u7089",
    "\u662f\u4ec0\u4e48", "\u662f\u591a\u5c11", "\u80fd\u5426", "\u80fd\u4e0d\u80fd", "\u53ef\u4ee5\u5417",
    "\u53ef\u4e0d\u53ef\u4ee5", "\u4f7f\u7528\u5417", "\u80fd\u7528\u5417", "\u53ef\u7528\u5417", "\u662f\u5426",
    "\u5982\u4f55\u4f7f\u7528", "\u600e\u6837\u4f7f\u7528", "\u5b89\u5168\u4f7f\u7528", "\u4f7f\u7528\u6ce8\u610f", "\u6ce8\u610f\u4e8b\u9879", "\u6ce8\u610f\u4ec0\u4e48",
)


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


def should_retrieve_experience_guidance(question: str) -> bool:
    """Keep soft experience guidance on strategy questions, not direct facts."""
    query = " ".join(str(question or "").strip().split())
    if not query:
        return False
    if any(marker in query for marker in _STRATEGY_QUERY_MARKERS):
        return True
    return not any(
        marker in query
        for marker in (*_FACT_QUERY_MARKERS, *_DIRECT_FACT_QUERY_MARKERS)
    )


def _approved_guidance_row(row: dict[str, Any]) -> bool:
    if str(row.get("source_type") or "").strip() != knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE:
        return False
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return (
        metadata.get("fact_authority") is False
        and str(metadata.get("authority_level") or "").strip() == _AUTHORITY_LEVEL
        and str(metadata.get("review_status") or "").strip() in _APPROVED_REVIEW_STATUSES
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
        not normalized_skus
        and len(approved_ranked_rows) >= 2
        and approved_ranked_rows[0][0] - approved_ranked_rows[1][0] < min_margin
    ):
        return []

    output_ranked_rows = approved_ranked_rows
    if normalized_skus:
        bound_ranked_rows = [
            item for item in approved_ranked_rows
            if str(item[2].get("sku") or "").strip().upper() in normalized_skus
        ]
        global_ranked_rows = [
            item for item in approved_ranked_rows
            if not str(item[2].get("sku") or "").strip()
        ]
        # An explicit SKU is a stronger scope signal than a small score
        # difference against a generic global card. Put the best same-SKU
        # guidance first, then use remaining slots for global strategy.
        output_ranked_rows = [*bound_ranked_rows, *global_ranked_rows]

    for _score, _index, row in output_ranked_rows:
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
