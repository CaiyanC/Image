"""A separate, conversational semantic-RAG customer-service runtime.

This path is intentionally smaller than the planner/writer pipeline used by
the existing semantic-RAG baseline.  It lets one governed LLM understand the
turn after retrieval instead of spending a second LLM call on a serialized
plan.  Retrieval remains the source of product facts, and the runtime keeps
conversation state isolated by pipeline.

There is no legacy intent router, keyword answer route, formatter, arbiter, or
polish pass in this module.  The small amount of code around the model is only
for retrieval, identity/provenance, safety boundaries, and persistence.
"""

from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any, Awaitable, Callable

from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.knowledge_base import CustomerServiceConversation, CustomerServiceMessage
from ..models.product import Product
from . import (
    customer_agent_service,
    customer_enterprise_guardrail_service,
    customer_experience_rag_service,
    customer_llm_service,
    customer_perf_service,
    customer_pipeline_service,
    knowledge_service,
    product_service,
)
from .customer_service_semantic_rag_v2_service import (
    _build_evidence,
    _clip_text,
    _compact_product_detail,
    _explicit_skus,
    _extract_json_object,
    _load_conversation_context,
    _normalize_skus,
    _product_identity,
    _public_result,
    _rank_retrieved_skus,
)


PIPELINE_VERSION = customer_pipeline_service.WORKBUDDY_RAG_PIPELINE
_MAX_HISTORY_MESSAGES = max(
    int(getattr(settings, "CUSTOMER_SERVICE_V2_MAX_HISTORY_MESSAGES", 12)),
    2,
)
_MAX_RETRIEVAL_ROWS = max(
    min(int(getattr(settings, "CUSTOMER_SERVICE_WORKBUDDY_MAX_RETRIEVAL_ROWS", 16)), 16),
    8,
)
_MAX_PROFILE_RETRIEVAL_ROWS = 48
_MAX_PROMPT_HISTORY_MESSAGES = 4
_MAX_PROMPT_CANDIDATE_PRODUCTS = 8
_MAX_PROMPT_EVIDENCE_ROWS = 10
_MAX_PROMPT_EVIDENCE_CONTENT = 420
_MAX_CANDIDATE_SKUS = 8
_WORKBUDDY_ANSWER_MAX_TOKENS = max(
    int(getattr(settings, "CUSTOMER_SERVICE_WORKBUDDY_MAX_ANSWER_TOKENS", 320)),
    256,
)
_WORKBUDDY_REASONING_EFFORT = (
    str(getattr(settings, "CUSTOMER_SERVICE_WORKBUDDY_REASONING_EFFORT", "none") or "")
    .strip()
    .lower()
    or None
)
_ANSWER_TYPES = frozenset({
    "product_detail",
    "recommendation",
    "comparison",
    "faq",
    "clarification",
})
_IDENTITY_RESOLUTIONS = frozenset({"resolved", "ambiguous", "unresolved"})
_SUBJECT_SCOPES = frozenset({"general_guidance", "product_specific", "catalogue"})
_SELECTION_STATES = frozenset({"selected", "candidate_only", "no_match", "not_applicable"})


def _compact_prompt_value(
    value: Any,
    *,
    string_limit: int = 720,
    list_limit: int = 8,
    dict_limit: int = 24,
    depth: int = 0,
) -> Any:
    """Keep the answer packet complete enough for facts without huge prompts.

    Product detail fields contain a mixture of plain text and JSON-encoded
    lists.  Compacting those values for the LLM packet reduces latency while
    preserving structured list members and both ends of long instructions.
    This is prompt shaping only; the full evidence remains in the public
    response and persistence record.
    """
    if depth > 4:
        return _clip_text(value, string_limit)
    if isinstance(value, dict):
        return {
            str(key): _compact_prompt_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
                depth=depth + 1,
            )
            for key, item in list(value.items())[:dict_limit]
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _compact_prompt_value(
                item,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
                depth=depth + 1,
            )
            for item in list(value)[:list_limit]
        ]
    if isinstance(value, str):
        text = value.strip()
        if len(text) <= string_limit:
            return text
        head = max(string_limit // 2, 1)
        tail = max(string_limit - head - 1, 1)
        return f"{text[:head].rstrip()}…{text[-tail:].lstrip()}"
    return value


def _compact_product_for_prompt(detail: dict[str, Any]) -> dict[str, Any]:
    """Expose answerable product facts without sending marketing prose twice.

    The answer model already receives retrieved QA/listing chunks below.  A
    full product detail beside those chunks made the prompt large and, more
    importantly, gave business positioning the same visual weight as factual
    fields.  Keep the canonical fields and the small amount of context needed
    for recommendations, while leaving long copy to RAG evidence.
    """
    compact = _compact_product_detail(detail)
    specs = compact.get("specs") if isinstance(compact.get("specs"), dict) else {}
    business = compact.get("business") if isinstance(compact.get("business"), dict) else {}
    return _compact_prompt_value({
        "evidence_role": "canonical_product_record",
        "authority_level": "canonical",
        "sku": compact.get("sku"),
        "product_name_cn": compact.get("product_name_cn"),
        "product_name_en": compact.get("product_name_en"),
        "brand": compact.get("brand"),
        "series": compact.get("series"),
        "category": compact.get("category"),
        "sub_category": compact.get("sub_category"),
        "specs": {
            "capacity": specs.get("capacity"),
            "gross_weight_g": specs.get("gross_weight_g"),
            "body_material": specs.get("body_material"),
            "color": specs.get("color"),
            "surface_finish": specs.get("surface_finish"),
            "heat_source": specs.get("heat_source"),
            "power": specs.get("power"),
            "size_info": specs.get("size_info"),
            "technical_advantages": specs.get("technical_advantages"),
        },
        "business": {
            "top_selling_points": business.get("top_selling_points"),
            "target_audience": business.get("target_audience"),
            "usage_scenarios": business.get("usage_scenarios"),
        },
    }, string_limit=120, list_limit=8, dict_limit=20)


def _evidence_authority_metadata(
    source_type: str,
    metadata: dict[str, Any],
    retrieval_role: str,
) -> tuple[str, str, bool]:
    """Describe provenance without deciding which answer the customer wants.

    The answer model needs to distinguish a live canonical record from a
    customer-facing QA snapshot and a retrieval-only recommendation profile.
    This is source provenance, not a question classifier or a keyword route.
    """
    explicit_level = str(metadata.get("authority_level") or "").strip().lower()
    if explicit_level in {"canonical", "catalogue", "supplemental", "candidate_only"}:
        level = explicit_level
    elif source_type == "product_record":
        level = "canonical"
    elif retrieval_role == "recommendation_candidate_recall":
        level = "candidate_only"
    else:
        section = str(metadata.get("section") or "").strip().lower()
        if section.startswith("qa:") or section == "qa":
            level = "supplemental"
        elif source_type == "product":
            level = "catalogue"
        else:
            level = "supplemental"
    role = str(metadata.get("authority") or "").strip()
    if not role:
        role = {
            "canonical": "canonical_product_record",
            "catalogue": "product_catalogue_record",
            "supplemental": "same_sku_product_qa",
            "candidate_only": "recommendation_candidate_recall",
        }[level]
    if "fact_authority" in metadata:
        fact_authority = bool(metadata.get("fact_authority"))
    else:
        fact_authority = level != "candidate_only"
    return role, level, fact_authority


def _compact_history_for_prompt(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve recent discourse context without replaying whole answers."""
    result: list[dict[str, Any]] = []
    for item in history[-_MAX_PROMPT_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = _clip_text(item.get("content"), 720)
        if role not in {"user", "assistant"} or not content:
            continue
        result.append({
            "role": role,
            "content": content,
            "sku": str(item.get("sku") or "").strip().upper() or None,
        })
    return result


def _compact_evidence_for_prompt(
    evidence: list[dict[str, Any]],
    *,
    visible_product_skus: set[str],
) -> list[dict[str, Any]]:
    """Keep a small, provenance-labelled RAG packet for the answer model.

    Retrieval has already fused vector and lexical signals.  The answer model
    needs the ranked evidence, not every duplicate listing paragraph or the
    full metadata JSON attached to it.  This is generic packet shaping: it
    does not inspect product names, question words, or answer types.
    """
    # A product_record is the canonical same-SKU fact source.  The old
    # compaction path dropped every product_record whenever a QA row existed,
    # which meant a natural question could see a plausible QA but not the
    # authoritative product fields.  Keep visible canonical records first,
    # then RAG rows, and finally any remaining records.  This is packet
    # ordering only; it does not classify the question or choose an answer.
    record_rows = [
        item for item in evidence
        if str(item.get("source_type") or "").strip() == "product_record"
    ]
    visible_record_rows = [
        item for item in record_rows
        if str(item.get("sku") or "").strip().upper() in visible_product_skus
    ]
    other_rows = [
        item for item in evidence
        if str(item.get("source_type") or "").strip() != "product_record"
    ]
    remaining_record_rows = [
        item for item in record_rows
        if str(item.get("sku") or "").strip().upper() not in visible_product_skus
    ]
    rows = [*visible_record_rows, *other_rows, *remaining_record_rows]
    compact_rows: list[dict[str, Any]] = []
    for item in rows:
        if len(compact_rows) >= _MAX_PROMPT_EVIDENCE_ROWS:
            break
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        section = str(metadata.get("section") or "").strip()
        retrieval_role = str(metadata.get("retrieval_role") or "").strip()
        content = item.get("content")
        source_type = str(item.get("source_type") or "knowledge").strip()
        sku = str(item.get("sku") or "").strip().upper() or None
        authority_role, authority_level, fact_authority = _evidence_authority_metadata(
            source_type,
            metadata,
            retrieval_role,
        )
        # The same canonical product record is already present in
        # candidate_products/previous_context_products.  Sending it a second
        # time in evidence made recommendation prompts disproportionately large
        # (and increased Luna latency) without adding a new fact.  Keep the
        # provenance row and let the answer model use the same-SKU canonical
        # packet for its fields.  This is generic evidence packing; it does not
        # select a product or inspect question wording.
        if source_type == "product_record" and sku in visible_product_skus:
            compact_content: Any = {
                "sku": sku,
                "canonical_record_pointer": True,
                "facts_in": "candidate_products",
            }
        elif isinstance(content, (dict, list, tuple, set)):
            compact_content: Any = _compact_prompt_value(
                content,
                string_limit=140,
                list_limit=8,
                dict_limit=20,
            )
        else:
            compact_content = _clip_text(content, _MAX_PROMPT_EVIDENCE_CONTENT)
        compact_rows.append({
            "evidence_id": str(item.get("evidence_id") or "").strip(),
            "sku": sku,
            "source_type": source_type,
            "source_id": str(item.get("source_id") or "").strip() or None,
            "content": compact_content,
            "score": item.get("score"),
            "source_section": _clip_text(section, 80),
            "source_title": _clip_text(metadata.get("title"), 120),
            "retrieval_role": _clip_text(retrieval_role, 80),
            "authority_role": authority_role,
            "authority_level": authority_level,
            "fact_authority": bool(fact_authority),
        })
    return compact_rows


def _normalize_working_memory_update(
    value: Any,
    *,
    result_skus: list[str],
    candidate_skus: list[str],
) -> dict[str, Any]:
    """Keep the model's small discourse memory safe and bounded.

    This is deliberately a shape/provenance boundary, not a decision maker.
    The answer model owns the meaning of the memory.  The server only keeps
    confirmed references inside ``result_skus`` and candidate references
    inside this turn's recalled SKU set, so a malformed model field cannot
    become a new product fact on the next turn.
    """
    source = value if isinstance(value, dict) else {}
    confirmed = list(dict.fromkeys(result_skus))
    candidates = list(dict.fromkeys([*result_skus, *candidate_skus]))

    raw_active = source.get("active_product_skus")
    active_product_skus = (
        confirmed
        if raw_active is None
        else [
            sku
            for sku in _normalize_skus(raw_active, limit=8)
            if sku in set(confirmed)
        ]
    )
    raw_candidates = source.get("candidate_product_skus")
    candidate_product_skus = (
        candidates
        if raw_candidates is None
        else [
            sku
            for sku in _normalize_skus(raw_candidates, limit=8)
            if sku in set(candidates)
        ]
    )
    return {
        "active_product_skus": active_product_skus[:8],
        "candidate_product_skus": candidate_product_skus[:8],
        "open_reference": _clip_text(source.get("open_reference"), 300),
        "transition": _clip_text(source.get("transition"), 300),
        "note": _clip_text(source.get("note"), 500),
    }


def _load_previous_turn_memory(
    db: Session,
    *,
    user_id: str,
    conversation_id: str | None,
) -> dict[str, Any]:
    """Load the last model-produced discourse memory for this pipeline.

    The memory is context for the next LLM turn, never an answer route.  A
    confirmed product reference is kept separately from recalled candidates;
    that distinction prevents a failed "换一款" turn from becoming a made-up
    replacement later without requiring a keyword rule.
    """
    if not conversation_id:
        return {}
    row = (
        db.query(CustomerServiceMessage)
        .join(
            CustomerServiceConversation,
            CustomerServiceConversation.id == CustomerServiceMessage.conversation_id,
        )
        .filter(
            CustomerServiceMessage.conversation_id == conversation_id,
            CustomerServiceMessage.role == "assistant",
            CustomerServiceConversation.user_id == str(user_id),
            CustomerServiceConversation.pipeline == PIPELINE_VERSION,
        )
        .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
        .first()
    )
    if row is None:
        return {}
    try:
        sources = json.loads(row.sources_json or "[]")
    except (TypeError, ValueError):
        sources = []
    if not isinstance(sources, list):
        return {}
    meta = next(
        (
            item for item in sources
            if isinstance(item, dict) and item.get("type") == "agent_meta"
        ),
        None,
    )
    if not isinstance(meta, dict):
        return {}
    answer_metadata = meta.get("answer_metadata") if isinstance(meta.get("answer_metadata"), dict) else {}
    result_skus = _normalize_skus(meta.get("result_skus"), limit=8)
    candidate_skus = _normalize_skus(meta.get("candidate_skus"), limit=8)
    memory = _normalize_working_memory_update(
        answer_metadata.get("working_memory_update"),
        result_skus=result_skus,
        candidate_skus=candidate_skus,
    )
    # Older turns do not have a memory update.  The persisted result/candidate
    # fields still provide a lossless, provenance-labelled fallback while the
    # next answer model learns the richer memory shape.
    memory.update({
        "last_question": _clip_text(answer_metadata.get("user_question"), 500),
        "answer_excerpt": _clip_text(row.content, 720),
    })
    return memory


def _unique_queries(question: str, history: list[dict[str, Any]]) -> list[str]:
    """Use the customer's current turn as the retrieval query.

    Conversation history is sent to the answer model as discourse context.
    Concatenating old questions into the vector query made unrelated earlier
    topics compete with the current request and could retrieve a different
    SKU's facts.  A follow-up still has its confirmed product in the evidence
    packet through ``previous_turn_memory`` and ``candidate_products``.
    ``history`` remains in the signature so the retrieval/answer boundary is
    explicit at the call site; it is intentionally not flattened into text.
    """
    del history
    current = _clip_text(question, 1000)
    return [current] if current else []


def _context_skus(context_candidates: list[dict[str, str]]) -> list[str]:
    return list(dict.fromkeys(
        str(item.get("sku") or "").strip().upper()
        for item in context_candidates
        if str(item.get("sku") or "").strip()
    ))[:5]


def _catalogue_subject_skus(db: Session, question: str) -> list[str]:
    """Recall product identities named in the current turn from the master.

    This is an identity/evidence pre-pass, not a customer-intent route.  The
    existing catalogue resolver compares the complete customer wording with
    the live product names and their normalized display aliases; the answer
    model still decides whether the candidates actually answer the question.
    Keeping this pass separate from ``retrieved_skus`` prevents a related QA
    (for example, another lightweight item) from replacing a named product
    before the RAG packet reaches the model.
    """
    text = str(question or "").strip()
    if not text:
        return []
    try:
        products = db.query(Product).all()
        candidates = customer_agent_service.resolve_named_product_candidates(
            text,
            products,
        )
    except Exception as exc:
        customer_perf_service.log_event(
            "customer_service_workbuddy.catalogue_subject_error",
            error=type(exc).__name__,
        )
        return []
    return list(dict.fromkeys(
        str(product.sku or "").strip().upper()
        for product in candidates
        if str(product.sku or "").strip()
    ))[:_MAX_CANDIDATE_SKUS]


def _normalize_retrieved_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for rank, raw in enumerate(rows or []):
        if not isinstance(raw, dict):
            continue
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        source_type = str(raw.get("source_type") or "knowledge").strip()
        sku = str(raw.get("sku") or "").strip().upper() or None
        source_id = str(
            metadata.get("source_id")
            or raw.get("source_id")
            or raw.get("content")
            or ""
        ).strip()
        identity = (source_type, sku or "", source_id)
        if identity in seen:
            continue
        seen.add(identity)
        result.append({
            "source_type": source_type,
            "sku": sku,
            "source_id": source_id or None,
            "content": _clip_text(raw.get("content"), 1800),
            "metadata": metadata,
            "score": raw.get("score"),
            "retrieval_rank": rank,
        })
    return result


async def _retrieve_once(
    db: Session,
    *,
    query: str,
    sku: str | None = None,
    skus: list[str] | None = None,
    sections: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    start = perf_counter()
    try:
        rows = await knowledge_service.semantic_retrieve(
            db,
            query,
            sku=sku,
            skus=skus,
            limit=max(int(limit or _MAX_RETRIEVAL_ROWS), 1),
            prefer_product_sources=bool(sku or skus or sections),
            sections=sections,
        )
    except Exception as exc:
        customer_perf_service.log_event(
            "customer_service_workbuddy.retrieval_error",
            error=type(exc).__name__,
        )
        rows = []
    normalized = _normalize_retrieved_rows(rows)
    customer_perf_service.log_stage(
        "customer_service_workbuddy.semantic_retrieve",
        start,
        query=_clip_text(query, 180),
        sku=sku,
        skus=skus or [],
        sections=sections or [],
        rows=len(normalized),
    )
    return normalized


def _fused_retrieved_skus(
    sources: list[list[dict[str, Any]]],
    *,
    limit: int = _MAX_CANDIDATE_SKUS,
) -> list[str]:
    """Fuse independent RAG pages at SKU level without semantic routing.

    The question page contains narrow QA hits while the profile page contains
    complete live product records.  Keeping each page as an independent rank
    signal prevents repeated chunks from one product from hiding a relevant
    SKU recalled by the other page; the LLM still owns the final choice.
    """
    annotated: list[dict[str, Any]] = []
    for source_index, rows in enumerate(sources):
        for rank, row in enumerate(rows or []):
            if not isinstance(row, dict):
                continue
            annotated.append({
                **row,
                "retrieval_query_index": f"workbuddy_source:{source_index}",
                "retrieval_rank": rank,
            })
    return _rank_retrieved_skus(annotated, limit=limit)


def _retrieved_skus(
    rows: list[dict[str, Any]],
    *,
    limit: int = _MAX_CANDIDATE_SKUS,
) -> list[str]:
    return list(dict.fromkeys(
        str(row.get("sku") or "").strip().upper()
        for row in rows
        if str(row.get("sku") or "").strip()
    ))[:limit]


def _append_same_sku_context(
    db: Session,
    rows: list[dict[str, Any]],
    sku: str,
) -> None:
    for row in knowledge_service.same_sku_customer_context(db, sku, limit=2):
        if not isinstance(row, dict):
            continue
        rows.append({
            "source_type": row.get("source_type") or "product",
            "sku": sku,
            "source_id": (
                str((row.get("metadata") or {}).get("source_id") or "").strip() or None
                if isinstance(row.get("metadata"), dict)
                else None
            ),
            "content": _clip_text(row.get("content"), 1800),
            "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
            "score": row.get("score"),
            "retrieval_rank": -1,
        })


def _product_details(
    db: Session,
    skus: list[str],
    *,
    limit: int = 10,
) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    for sku in skus[:limit]:
        try:
            detail = product_service.get_product_detail(db, sku)
        except Exception:
            continue
        if isinstance(detail, dict):
            details[sku] = detail
    return details


def _answer_prompt(
    *,
    question: str,
    history: list[dict[str, Any]],
    previous_turn_memory: dict[str, Any],
    context_candidates: list[dict[str, str]],
    explicit_product_skus: list[str],
    catalogue_subject_skus: list[str] | None = None,
    anchor_skus: list[str],
    page_anchor: dict[str, str] | None,
    candidates: list[dict[str, Any]],
    previous_context_products: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    experience_guidance: list[dict[str, Any]],
    active_context_products: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt_candidates = [
        item for item in candidates[:_MAX_PROMPT_CANDIDATE_PRODUCTS]
        if isinstance(item, dict)
    ]
    compact_candidates = [
        _compact_product_for_prompt(item)
        for item in prompt_candidates
    ]
    compact_previous_products = [
        _compact_product_for_prompt(item)
        for item in previous_context_products
        if isinstance(item, dict)
    ]
    compact_active_context_products = [
        _compact_product_for_prompt(item)
        for item in (active_context_products or [])
        if isinstance(item, dict)
    ]
    visible_product_skus = {
        str(item.get("sku") or "").strip().upper()
        for item in [*prompt_candidates, *previous_context_products]
        if isinstance(item, dict) and str(item.get("sku") or "").strip()
    }
    compact_evidence = _compact_evidence_for_prompt(
        [item for item in evidence if isinstance(item, dict)],
        visible_product_skus=visible_product_skus,
    )
    return {
        "current_question": question,
        "page_anchor": page_anchor or {},
        "explicit_product_skus": explicit_product_skus,
        "catalogue_subject_skus": list(catalogue_subject_skus or []),
        "catalogue_identity_context": {
            "role": "retrieval_identity_hint_only",
            "skus": list(catalogue_subject_skus or []),
            "not_customer_confirmed": True,
            "guidance": (
                "这是目录身份召回提示，不是客户已确认的商品，也不是最终选择；"
                "candidate_products 和 evidence 才是本轮可核对的资料。"
            ),
        },
        "identity_resolution_context": {
            "selection_owner": "answer_llm",
            "unanchored_candidate_set": not bool(
                explicit_product_skus or anchor_skus or page_anchor
            ),
            "catalogue_hint_skus": list(catalogue_subject_skus or []),
            "candidate_skus": [
                str(item.get("sku") or "").strip().upper()
                for item in prompt_candidates
                if isinstance(item, dict) and str(item.get("sku") or "").strip()
            ],
            "guidance": (
                "候选集合用于语义判断，不按顺序或单一提示自动确认。"
                "如果多个同名、同系列或变体都能支持当前问题的共同事实，可以合并回答并列出对应 SKU；"
                "如果身份或配置会改变答案，再简短澄清。"
            ),
        },
        "context_product_skus": anchor_skus,
        "conversation_history": _compact_history_for_prompt(history),
        "previous_turn_memory": _compact_prompt_value(
            previous_turn_memory,
            string_limit=520,
            list_limit=8,
            dict_limit=12,
        ),
        "previous_result_candidates": context_candidates,
        "previous_context_products": compact_previous_products,
        "active_context_products": compact_active_context_products,
        "active_context_contract": (
            "本轮问题中的代词或‘刚才两款/上一轮’默认指向这些已确认的上下文商品。"
            "只有客户明确要求换一款、寻找其他商品或扩大推荐范围时，才把其他候选作为新的选择空间；"
            "否则不要用新召回候选替换上下文参与者。"
            if compact_active_context_products
            else ""
        ),
        "candidate_products": compact_candidates,
        "evidence": compact_evidence,
        "turn_identity_contract": {
            "customer_identity_bound": bool(
                explicit_product_skus
                or page_anchor
                or catalogue_subject_skus
                or active_context_products
            ),
            "explicit_product_skus": list(explicit_product_skus),
            "catalogue_subject_skus_are_hints_only": True,
            "candidate_skus_are_not_customer_selection": True,
            "unbound_turn_guidance": (
                "如果 customer_identity_bound=false，且当前问题是通用安全、使用或清洁做法，"
                "按 general_guidance 回答，subject_scope=general_guidance、selected_skus=[]、"
                "selection_state=not_applicable；可使用证据回答共同原则，但不能因为证据行带 SKU 就把客户绑定到该商品。"
                "如果问题是收货后少件、破损、功能异常或售后处理，且商品身份仍未确认，"
                "只能先承接问题并请求商品名/SKU、订单信息和具体现象；不要从候选商品中挑选或并列引用某个商品的售后政策。"
            ),
        },
        "experience_guidance": experience_guidance,
    }


async def _generate_answer(
    db: Session,
    *,
    payload: dict[str, Any],
    answer_delta_callback: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    system_prompt = (
        "【热源兼容事实边界】先按本轮要回答的具体 SKU 核对热源字段：客户问‘能用 X 吗/兼容 X 吗/适配什么燃料’时，只有该 SKU 的 evidence 在适用热源或使用说明中明确写出 X，才能回答支持；未写出就回答‘未列出/暂不能确认’，不能用常识补全。‘明火直烧’、‘开放火焰’、‘燃气’、‘多种热源’都不能自动推出酒精炉、燃气炉、木柴、木炭或电磁炉等具体选项。另一个 SKU 的 evidence 只能说明另一个 SKU，不能替当前 SKU 作兼容证明。若同 SKU 使用说明明确写出酒精炉/燃气炉版本，则可以按该版本回答，但仍要说明以所购版本和配置为准。这个边界优先级高于营销文案、候选列表和经验建议。\n"
        "先判断当前消息的完整语义：明确 SKU 或商品对象后继续询问容量、重量、净重/毛重、材质、热源、尺寸、配件、适配、使用或清洁，"
        "都是事实问题，必须依据本轮 evidence 回答；不要把‘SKU + 事实问题’误读成‘请记住这个 SKU’。只有客户明确要求记住/保留，且没有提出事实问题时，才走记忆确认。"
        "语义示例：‘CW-C78的重量是多少？’应回答本轮证据中的重量；‘CW-C78的净重是多少？’应核对后说明资料是否标注净重；"
        "‘CW-C69-1和CW-C06PRO容量和重量怎么比较？’应基于两款各自证据比较；‘请记住CW-C78，后面再比较’才只确认记忆。"
        "这些是帮助理解任务的示例，不是客户问法路由。"
        "当 identity_resolution_context.unanchored_candidate_set=true 时，本轮没有已确认的商品身份，"
        "candidate_products 只是候选集合，最终选择必须由你结合当前问题语义完成。若客户问的是一组或套装，"
        "不能只引用单品卡；从候选资料中判断相关套装变体，事实相同可合并回答并列出对应 SKU，事实不同再澄清。\n"
        "如果 catalogue_subject_skus 非空，且结合当前问题语义可以确认它只对应一个商品主体，或某个主体的当前 evidence 已足以回答，"
        "不要把这条明确的商品问题泛化为 general_guidance；应按 product_specific 处理，保留该主体的商品名/SKU并回答其同 SKU 事实。"
        "catalogue_subject_skus 仍只是身份提示，不能单独替代 evidence，也不能按列表顺序自动选择；是否确认仍由你结合完整语境和当前 evidence 判断。"
        "例如当前问题是‘享野套锅每次用完怎么洗’，且 catalogue_subject_skus/evidence 指向 CW-C78 时，应保留 CW-C78 并回答该套锅的清洗资料，不能改写成‘一般锅具’。"
        "若客户只是明确给出一个或多个完整 SKU，并要求先记住、保留或作为后续比较对象，而不是询问商品事实，"
        "请自然确认记忆，使用 answer_type=faq、needs_clarification=false；不要把这类记忆动作回复成澄清。"
        "如果同一条消息同时给出了商品标识和商品事实、参数、使用或适配问题，事实问题优先；"
        "不要因为出现完整 SKU 就把它当成‘请记住这款’，必须依据本轮 evidence 回答该问题。"
        "当 explicit_product_skus 为空、page_anchor 为空、active_context_products 为空，且当前问题本身没有明确指向某一件商品时，"
        "如果客户是在询问通用的安全、使用或清洁做法，请按 general_guidance 处理：subject_scope=general_guidance、"
        "selected_skus=[]、selection_state=not_applicable，不要因为某一条商品说明带有 SKU 就把泛问题绑定到该商品，"
        "也不要在通用答案后追加‘某 SKU 已确认’的条件式商品结论。可以综合多条一致的资料回答共同原则；只有客户明确给出商品、"
        "已有上下文商品会改变结论，或答案必须区分具体商品时，才在证据支持下列出 SKU。"
        "若当前问法带有版本、代际、变体或组件限定，而 evidence 没有明确覆盖同一限定，答案必须直接说明只能确认未带该限定的基础资料，"
        "不能先说‘可以按该版本回答’再用附带说明弱化，也不能把基础款事实升级成具体版本结论。\n"
        "catalogue_subject_skus 只是目录身份召回提示，不是客户已确认的商品，也不是最终选择；"
        "不要因为提示列表第一项或检索分数最高就默默选中一个 SKU。若 candidate_products 中有多个同名、同系列或变体，"
        "请结合当前问题和各自 evidence 语义判断：共同事实可以合并回答并列出对应 SKU，身份或配置会改变答案时简短澄清。"
        "问题中的版本、代际、变体或组件限定只有在 evidence 明确覆盖同一限定时才能套用；"
        "若资料只覆盖基础型号，就说明资料覆盖范围，不要把基础型号事实升级成未确认版本的结论。"
        "开放式推荐若没有额外偏好，只要有可核对的候选，就按完整需求语义选出合适候选并说明依据；"
        "不要因为缺少非必要偏好直接说没有依据，也不要按召回顺序机械推荐。\n"
        "你是自然、连贯、像真人同事一样工作的中文客服。先理解当前问题、conversation_history 和 previous_turn_memory，再依据本轮 evidence 与 candidate_products 回答；不要向客户暴露内部字段、检索、模型或流程。"
        "请同时遵守 payload.turn_identity_contract：它是本轮客户身份与候选证据的语义边界；customer_identity_bound=false 时，候选 SKU 只能作为证据来源，不能当作客户已选商品。"
        "若 payload 提供 active_context_products，‘它/这款/刚才两款/上一轮’等上下文指代优先在这些商品内理解；只有客户明确要求换一款、其他选择或扩大推荐时，才引入其他候选。不要让新召回候选静默替换上一轮比较参与者。"
        "experience_guidance 是人工审核提炼的非事实沟通经验，只能帮助你更自然地承接顾虑、组织取舍和给出下一步；不能证明商品事实、不能替代 evidence、不能选择 SKU，也不能向客户提及。简单事实问题或不相关建议应直接忽略，不要强行推销或增加篇幅。完整回答当前问题的前提下优先三到六句短答，复杂比较确有必要时再用少量条目。"
        "历史和记忆只用于理解代词、承接上下文和替换意图，不是新的商品事实；商品事实只能来自本轮 evidence，并保留它所属的 SKU。canonical_product_record 是结构化主数据，product_qa 是同 SKU 补充；出现直接冲突时如实说明资料差异。"
        "canonical_product_record 对同一 SKU 的非空结构化字段拥有最高事实权威；同 SKU QA/知识只能补充主数据未填写的事实，不能静默改写主数据。适用热源等封闭兼容字段只认可资料明确列出的具体选项，‘明火’或‘燃气’等宽泛词不能推出具体的酒精炉等选项；空值、‘/’、暂无或未知表示主数据未填写，不是通用兼容。只有同 SKU 主数据该字段为空时，才可按已审核 QA 明确列出的范围补充并提示主数据待补充；同一封闭字段一旦已有非空主数据，即使 QA 已审核，也不能把 QA 追加的具体选项当作扩展兼容；两者不一致时以主数据为准并说明资料差异。不要把这种情况误称为直接冲突，也不能扩大 QA 的范围。热源兼容不等于室内使用许可：只有同 SKU 证据明确说明室内或家用场景时才能回答可以室内使用；仅有热源、露营或户外资料时，不得推导室内可用或室内安全，应说明资料未直接确认并提醒遵守炉具通风和安全要求。"
        "回答内容优先。若多个候选对客户当前询问的同一事实都有明确且一致的资料，可以直接回答共同事实，并列出实际支持该回答的 SKU；不要因为召回多个 SKU 就机械澄清。只有商品身份、必要条件或事实确实存在歧义/缺失时才澄清；资料不足时说明边界，不要编造。重量、容量、尺寸不能自行升级成‘无负担、一定适合、完全满足’等更强结论。"
        "推荐或比较可以引用多个候选，但只能使用 evidence 中实际存在的 SKU，不要按候选排序自动推荐。普通安全/使用问题直接依据资料回答。不要为了填写分类、选卡或记忆字段而改变一个本来可用的回答，也不要为了填字段编造事实。"
        "只输出一个 JSON 对象，唯一必填字段是 answer；其余字段全部可选，仅在确实有助于证据归因、商品卡或下一轮承接时返回。下面的内部元数据没有把握时可以省略，不能因为填写它们而改变本来可用的自然回答。可选字段如下："
        '{"answer":"自然客服回复",'
        '"evidence_ids":["实际使用的 evidence_id"],'
        '"selected_skus":["明确回答或推荐所绑定的 evidence SKU"],'
        '"working_memory_update":{"active_product_skus":[],"candidate_product_skus":[],"open_reference":"","transition":"","note":""},'
        '"identity_resolution":"resolved|ambiguous|unresolved（仅在商品身份判断有帮助时返回）",'
        '"subject_scope":"general_guidance|product_specific|catalogue（可选）",'
        '"selection_state":"selected|candidate_only|no_match|not_applicable（可选）",'
        '"answer_type":"product_detail|recommendation|comparison|faq|clarification（可选）",'
        '"request_kind":"product_fact|product_qa|recommendation|comparison|general_knowledge|clarification（可选）",'
        '"needs_clarification":true或false,"confidence":"high|medium|low（可选）",'
        '"uncertainty":"confirmed|partial|unconfirmed（可选）",'
        '"suggested_followups":["确有帮助时再给自然追问"]}'
    )
    start = perf_counter()
    metadata: dict[str, Any] = {}
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ]
        if answer_delta_callback is None:
            raw_text = await customer_llm_service.chat_completion(
                db,
                messages=messages,
                temperature=0,
                max_tokens=_WORKBUDDY_ANSWER_MAX_TOKENS,
                purpose="customer_service_workbuddy_answer",
                response_format={"type": "json_object"},
                thinking={"type": "disabled"},
                reasoning_effort=_WORKBUDDY_REASONING_EFFORT,
                metadata=metadata,
            )
        else:
            raw_parts: list[str] = []
            emitted_answer = ""
            async for chunk in customer_llm_service.chat_completion_stream(
                db,
                messages=messages,
                temperature=0,
                max_tokens=_WORKBUDDY_ANSWER_MAX_TOKENS,
                purpose="customer_service_workbuddy_answer",
                response_format={"type": "json_object"},
                thinking={"type": "disabled"},
                reasoning_effort=_WORKBUDDY_REASONING_EFFORT,
                metadata=metadata,
            ):
                raw_parts.append(str(chunk))
                partial_answer = _partial_json_answer("".join(raw_parts))
                if (
                    partial_answer
                    and partial_answer.startswith(emitted_answer)
                    and len(partial_answer) > len(emitted_answer)
                ):
                    delta = partial_answer[len(emitted_answer):2400]
                    if delta:
                        await answer_delta_callback(delta)
                        emitted_answer += delta
            raw_text = "".join(raw_parts)
            metadata["answer_streamed"] = bool(emitted_answer)
        raw = _extract_json_object(raw_text)
        metadata["elapsed_ms"] = round(customer_perf_service.perf_ms(start), 2)
        metadata["raw_valid"] = bool(raw)
        return raw, metadata
    except Exception as exc:
        customer_perf_service.log_event(
            "customer_service_workbuddy.answer_error",
            error=type(exc).__name__,
            error_detail=_clip_text(str(exc), 200),
        )
        metadata.update({
            "elapsed_ms": round(customer_perf_service.perf_ms(start), 2),
            "raw_valid": False,
            "error": type(exc).__name__,
        })
        return None, metadata


def _partial_json_answer(raw_text: str) -> str:
    """Read the answer string while an OpenAI JSON stream is incomplete."""
    match = re.search(r'"answer"\s*:\s*"', raw_text)
    if not match:
        return ""
    cursor = match.end()
    chars: list[str] = []
    escaped = False
    while cursor < len(raw_text):
        char = raw_text[cursor]
        cursor += 1
        if escaped:
            if char == "n":
                chars.append("\n")
            elif char == "r":
                chars.append("\r")
            elif char == "t":
                chars.append("\t")
            elif char in {'"', "\\", "/"}:
                chars.append(char)
            elif char == "u" and cursor + 4 <= len(raw_text):
                codepoint = raw_text[cursor:cursor + 4]
                if not re.fullmatch(r"[0-9a-fA-F]{4}", codepoint):
                    break
                chars.append(chr(int(codepoint, 16)))
                cursor += 4
            else:
                # Do not expose an incomplete escape sequence to the client.
                break
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            break
        chars.append(char)
    return "".join(chars)


def _safe_missing_answer(*, has_identity_ambiguity: bool) -> str:
    if has_identity_ambiguity:
        return "我还不能确认你指的是哪一款商品。请补充商品名称或 SKU，我再按对应商品核对。"
    return "我查看了当前商品资料，但没有找到能直接确认这个问题的依据。你可以补充具体商品名称或 SKU，我再继续核对。"


def _normalize_identity_resolution(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _IDENTITY_RESOLUTIONS else "unresolved"


def _normalize_subject_scope(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _SUBJECT_SCOPES else ""


def _normalize_selection_state(
    value: Any,
    *,
    answer_type: str,
    selected_skus: list[str],
) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _SELECTION_STATES:
        return normalized
    if answer_type in {"recommendation", "comparison"}:
        return "selected" if selected_skus else "candidate_only"
    return "not_applicable"


def _validated_workbuddy_answer(
    raw: dict[str, Any] | None,
    *,
    evidence: list[dict[str, Any]],
    candidate_skus: list[str],
    identity_ambiguity: bool,
) -> tuple[str, str, bool, str, str, list[str], list[str], list[str]]:
    """Normalize the model contract without importing the baseline validator.

    This is deliberately limited to the evidence IDs/SKUs supplied in this
    turn and the public response shape.  It does not inspect answer wording,
    classify keywords, or promote a hard-coded product field route.
    """
    allowed_skus = {
        str(item.get("sku") or "").strip().upper()
        for item in evidence
        if str(item.get("sku") or "").strip()
    }
    evidence_ids = {
        str(item.get("evidence_id") or "").strip()
        for item in evidence
        if str(item.get("evidence_id") or "").strip()
    }
    value = raw if isinstance(raw, dict) else {}
    answer = _clip_text(value.get("answer"), 2400)
    selected_skus = [
        sku for sku in _normalize_skus(value.get("selected_skus"), limit=_MAX_CANDIDATE_SKUS)
        if sku in allowed_skus
    ]
    selected_evidence = [
        normalized_id
        for item in (
            [value.get("evidence_ids")]
            if isinstance(value.get("evidence_ids"), str)
            else value.get("evidence_ids") or []
        )
        if (normalized_id := _clip_text(item, 120)) and normalized_id in evidence_ids
    ][:12]
    answer_type = str(value.get("answer_type") or "").strip().lower()
    if answer_type not in _ANSWER_TYPES:
        # Missing optional metadata is not a reason to replace a usable model
        # answer with a canned clarification.  Only an actually empty answer
        # falls through to the safe response below.
        answer_type = "faq"
    # Keep the public contract internally consistent even when the answer
    # model forgets to mirror its own answer_type.  This is a response-shape
    # invariant, not a question classifier: a clarification must be exposed
    # as such to the UI and to the next-turn memory loader.
    needs_clarification = (
        bool(value.get("needs_clarification"))
        or answer_type == "clarification"
    )
    if not answer:
        answer = _safe_missing_answer(has_identity_ambiguity=identity_ambiguity)
        answer_type = "clarification"
        needs_clarification = True
    confidence = str(value.get("confidence") or "low").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    uncertainty = str(value.get("uncertainty") or "unconfirmed").strip().lower()
    if uncertainty not in {"confirmed", "partial", "unconfirmed"}:
        uncertainty = "unconfirmed"
    followups_value = value.get("suggested_followups")
    if isinstance(followups_value, str):
        followups_value = [followups_value]
    followups: list[str] = []
    for item in followups_value if isinstance(followups_value, list) else []:
        text = _clip_text(item, 240)
        if text and text not in followups:
            followups.append(text)
        if len(followups) >= 3:
            break
    # Result cards follow only the model's explicit, evidence-backed
    # selection.  ``selection_state`` remains observability metadata; it does
    # not rewrite the answer or route the turn.  In particular, a recalled
    # candidate is never promoted merely because it was the only row returned.
    # A clarification can cite the recalled evidence, but it has not confirmed
    # an answer object.  Do not render a recalled SKU as an already selected
    # product card; candidate_skus remains available for the next turn.
    # An unresolved identity may still have a useful natural answer (for
    # example, the model can explain that two recalled variants share a fact).
    # Do not show a product card or persist that candidate as confirmed unless
    # the semantic identity/provenance boundary was satisfied.
    result_skus = (
        []
        if answer_type == "clarification" or identity_ambiguity
        else selected_skus
    )
    return (
        answer,
        answer_type,
        needs_clarification,
        confidence,
        uncertainty,
        result_skus,
        selected_evidence,
        followups,
    )


def _pipeline_plan(
    raw: dict[str, Any] | None,
    *,
    question: str,
    queries: list[str],
    known_skus: list[str],
    candidate_skus: list[str],
) -> dict[str, Any]:
    allowed_kinds = {
        "product_fact",
        "product_qa",
        "recommendation",
        "comparison",
        "general_knowledge",
        "clarification",
    }
    raw_kind = str((raw or {}).get("request_kind") or "").strip().lower()
    kind = raw_kind if raw_kind in allowed_kinds else "general_knowledge"
    return {
        "request_kind": kind,
        "subject_scope": "known_product" if known_skus else ("catalogue" if candidate_skus else "unknown"),
        "subject_text": "",
        "search_queries": queries,
        "requested_dimensions": [],
        "response_focus": _clip_text(question, 500),
        "plan_available": bool(raw),
        "plan_owner": "answer_llm",
    }


def _retag_control_result(result: dict[str, Any]) -> dict[str, Any]:
    tagged = dict(result or {})
    metadata = dict(tagged.get("answer_metadata") or {})
    metadata.update({
        "pipeline_version": PIPELINE_VERSION,
        "semantic_owner": "control_boundary",
        "retrieval_mode": "control_boundary_no_retrieval",
    })
    tagged["answer_metadata"] = metadata
    debug = dict(tagged.get("debug") or {})
    debug.update({
        "pipeline_version": PIPELINE_VERSION,
        "agent_mode": PIPELINE_VERSION,
        "semantic_owner": "control_boundary",
        "no_legacy_route": True,
        "llm_call_count": 0,
    })
    tagged["debug"] = debug
    tagged["agent_mode"] = PIPELINE_VERSION
    tagged["pipeline_version"] = PIPELINE_VERSION
    tagged["skip_polish"] = True
    return tagged


async def _control_boundary_result(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None,
    conversation_id: str | None,
) -> dict[str, Any] | None:
    # WorkBuddy is an Agent-style conversational read path.  Use only the
    # narrow control-plane boundary here; the baseline's broader
    # ``evaluate_question`` also contains business/weather/creative/travel
    # shortcuts that would answer before RAG and turn this path back into a
    # deterministic router.
    guarded = customer_enterprise_guardrail_service.evaluate_hard_boundary(question)
    if guarded:
        return _retag_control_result(guarded)

    # Reuse only the confirmation-gated write/sensitive-data boundary. It is
    # not used to classify ordinary reads or to produce a product answer.
    from . import customer_service_service as shared_service

    try:
        proposal = await shared_service._try_explicit_customer_mutation_result(
            db,
            user_id=str(user_id),
            question=question,
            sku=sku,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        customer_perf_service.log_event(
            "customer_service_workbuddy.mutation_proposal_error",
            error=type(exc).__name__,
        )
        proposal = None
    if proposal:
        return _retag_control_result(proposal)

    try:
        mutation_boundary = shared_service._customer_mutation_boundary_result(question)
    except Exception as exc:
        customer_perf_service.log_event(
            "customer_service_workbuddy.mutation_boundary_error",
            error=type(exc).__name__,
        )
        mutation_boundary = None
    return _retag_control_result(mutation_boundary) if mutation_boundary else None


async def ask_customer_service_workbuddy_rag(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None = None,
    conversation_id: str | None = None,
    answer_delta_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    original_question = str(question or "").strip()
    if not original_question:
        raise ValueError("问题不能为空")
    request_start = perf_counter()

    control_result = await _control_boundary_result(
        db,
        user_id=str(user_id),
        question=original_question,
        sku=sku,
        conversation_id=conversation_id,
    )
    if control_result:
        return await _persist_result(
            db,
            user_id=str(user_id),
            question=original_question,
            conversation_id=conversation_id,
            agent_result=control_result,
            answer_delta_callback=answer_delta_callback,
        )

    page_sku = None
    if sku:
        normalized = str(sku).strip().upper()
        if db.query(Product).filter(Product.sku == normalized).first() is not None:
            page_sku = normalized

    page_product = db.query(Product).filter(Product.sku == page_sku).first() if page_sku else None
    page_anchor = _product_identity(page_product) or None
    history, context_candidates = _load_conversation_context(
        db,
        user_id=str(user_id),
        conversation_id=conversation_id,
        pipeline=PIPELINE_VERSION,
    )
    previous_turn_memory = _load_previous_turn_memory(
        db,
        user_id=str(user_id),
        conversation_id=conversation_id,
    )
    explicit_skus = _explicit_skus(db, original_question)
    known_skus = explicit_skus or ([page_sku] if page_sku else [])
    catalogue_subject_skus = (
        []
        if known_skus
        else _catalogue_subject_skus(db, original_question)
    )
    # Only a previously confirmed reference is an anchor.  Recalled
    # candidates remain visible to the answer model, but they must not scope
    # the next retrieval pass or turn a requested replacement into a made-up
    # active product.
    anchor_skus = (
        _normalize_skus(previous_turn_memory.get("active_product_skus"), limit=5)
        if not known_skus
        else []
    )
    queries = _unique_queries(original_question, history)

    # An explicit page/SKU identity scopes factual retrieval; conversational
    # memory and catalogue-name candidates do not create a hard catalogue
    # filter.  This lets a natural question recover the live product whose
    # profile/QA is most relevant instead of being trapped by a weak fuzzy
    # name candidate.
    retrieval_scope_skus = list(dict.fromkeys(known_skus))
    scoped_skus = retrieval_scope_skus
    question_rows = await _retrieve_once(
        db,
        query=queries[0] if queries else original_question,
        sku=retrieval_scope_skus[0] if len(retrieval_scope_skus) == 1 else None,
        skus=scoped_skus if len(scoped_skus) > 1 else None,
    )
    retrieval_rows = list(question_rows)
    profile_rows: list[dict[str, Any]] = []
    if not known_skus:
        # A single live-profile pass complements the narrow question page.
        # It is catalogue recall only: the answer model still has to select a
        # SKU and bind every factual claim to same-SKU evidence.
        profile_rows = await _retrieve_once(
            db,
            query=queries[0] if queries else original_question,
            sections=["profile"],
            limit=_MAX_PROFILE_RETRIEVAL_ROWS,
        )
        retrieval_rows.extend(profile_rows)
    retrieved_skus = _fused_retrieved_skus([question_rows, profile_rows])
    # A previous single-product/candidate context is the first discourse
    # reference for a follow-up.  Keep it in the candidate packet even when
    # the scoped RAG page returns a slightly different order.
    candidate_skus = list(dict.fromkeys(
        # Catalogue identity hints stay visible beside the fused RAG page so a
        # named family/variant cannot disappear merely because unrelated
        # question chunks occupied the first slots.  They remain candidates,
        # not a retrieval filter or a confirmed customer selection.
        [*known_skus, *anchor_skus, *catalogue_subject_skus, *retrieved_skus]
    ))[:_MAX_CANDIDATE_SKUS]
    context_skus = _context_skus(context_candidates)
    active_context_skus = (
        []
        if known_skus
        else list(dict.fromkeys([*anchor_skus, *context_skus]))[:_MAX_CANDIDATE_SKUS]
    )
    detail_skus = list(dict.fromkeys(
        known_skus + candidate_skus + context_skus
    ))[:10]
    product_details = _product_details(db, detail_skus, limit=10)
    # Add same-SKU QA/context before sealing the evidence packet.  Appending
    # after _build_evidence would make those rows invisible to the answer LLM,
    # which is exactly the failure mode this pipeline is meant to avoid.
    for known_sku in known_skus:
        _append_same_sku_context(db, retrieval_rows, known_sku)

    # Once the current wording names a catalogue subject, unrelated semantic
    # neighbours must not enter the fact packet.  The model can still see the
    # full candidate card set for semantic choice, while only these subject
    # SKUs can contribute customer-visible facts this turn.
    allowed_skus = set(known_skus or [*candidate_skus, *context_skus])
    evidence = _build_evidence(
        retrieval_rows,
        product_details,
        allowed_skus=allowed_skus,
        # Without an explicit product anchor, an unbound knowledge chunk can
        # be the authoritative answer to a general question (for example,
        # safety/use guidance).  Recalled product SKUs remain available as
        # candidates, but they must not hide generic RAG evidence merely
        # because retrieval also found product rows.  An explicit SKU keeps
        # the stricter same-product boundary.
        allow_unbound=not known_skus,
    )
    candidates = [product_details[item] for item in candidate_skus if item in product_details]
    previous_context_products = [
        product_details[item]
        for item in context_skus
        if item in product_details and item not in set(candidate_skus)
    ]
    active_context_products = [
        product_details[item]
        for item in active_context_skus
        if item in product_details
    ]
    experience_start = perf_counter()
    experience_guidance = await customer_experience_rag_service.retrieve_experience_guidance(
        db,
        question=queries[0] if queries else original_question,
        skus=known_skus or candidate_skus[:3] or context_skus[:3],
    )
    customer_perf_service.log_stage(
        "customer_service_workbuddy.experience_retrieve",
        experience_start,
        rows=len(experience_guidance),
    )
    payload = _answer_prompt(
        question=original_question,
        history=history,
        previous_turn_memory=previous_turn_memory,
        context_candidates=context_candidates,
        explicit_product_skus=known_skus,
        catalogue_subject_skus=catalogue_subject_skus,
        anchor_skus=anchor_skus,
        page_anchor=page_anchor,
        candidates=candidates,
        previous_context_products=previous_context_products,
        evidence=evidence,
        experience_guidance=experience_guidance,
        active_context_products=active_context_products,
    )
    answer_raw, answer_metadata = await _generate_answer(
        db,
        payload=payload,
        answer_delta_callback=answer_delta_callback,
    )

    raw_answer_type = str((answer_raw or {}).get("answer_type") or "").strip().lower()
    raw_identity_resolution = _normalize_identity_resolution(
        (answer_raw or {}).get("identity_resolution")
    )
    raw_subject_scope = _normalize_subject_scope((answer_raw or {}).get("subject_scope"))
    # This is a semantic identity boundary, not a keyword route. The answer
    # LLM is allowed to resolve a product name from the RAG packet even when
    # retrieval returned several candidates; the boundary only requires the
    # model to declare that resolution and bind it to matching evidence.
    allowed_evidence_skus = {
        str(item.get("sku") or "").strip().upper()
        for item in evidence
        if str(item.get("sku") or "").strip()
    }
    selected_skus_from_model = [
        sku
        for sku in _normalize_skus((answer_raw or {}).get("selected_skus"), limit=5)
        if sku in allowed_evidence_skus
    ]
    raw_selected_skus = set(selected_skus_from_model)
    raw_evidence_ids_value = (
        (answer_raw or {}).get("evidence_ids")
        if isinstance(answer_raw, dict)
        else []
    )
    if isinstance(raw_evidence_ids_value, str):
        raw_evidence_ids_value = [raw_evidence_ids_value]
    raw_selected_evidence_ids = {
        str(item or "").strip()
        for item in raw_evidence_ids_value or []
        if str(item or "").strip()
    }
    # ``evidence_ids`` is also a semantic selection made by the answer LLM.
    # Keep its order and use it as a provenance-backed supplement when a model
    # omits the redundant ``selected_skus`` field.  This is not SKU matching
    # or a product rule: an ID is usable only when the model explicitly chose
    # that ID from this turn's evidence packet.
    evidence_skus_selected_by_llm = list(dict.fromkeys(
        str(item.get("sku") or "").strip().upper()
        for item in evidence
        if str(item.get("evidence_id") or "").strip() in raw_selected_evidence_ids
        and str(item.get("sku") or "").strip()
    ))
    raw_request_kind = str((answer_raw or {}).get("request_kind") or "").strip().lower()
    product_scoped_request = raw_request_kind in {"product_fact", "product_qa"} or raw_answer_type == "product_detail"
    # A model can still emit one selected SKU while its natural answer asks
    # the customer to disambiguate (or while it mislabels a product question
    # as a FAQ). The explicit identity contract below keeps that draft from
    # becoming a bound product answer without using product-name/keyword
    # routing.
    model_selected_product = bool(raw_selected_skus or evidence_skus_selected_by_llm)
    semantic_selection_answer = raw_request_kind in {"recommendation", "comparison"} or raw_answer_type in {
        "recommendation",
        "comparison",
    }
    has_identity_anchor = bool(known_skus or anchor_skus)
    general_guidance_request = raw_subject_scope == "general_guidance" and not has_identity_anchor
    product_scoped_request = (
        not general_guidance_request
        and (
            product_scoped_request
            or (
                model_selected_product
                and not semantic_selection_answer
            )
        )
    )
    unanchored_product_detail = (
        not has_identity_anchor
        and not semantic_selection_answer
        and product_scoped_request
    )
    selected_skus_for_contract = list(
        selected_skus_from_model or evidence_skus_selected_by_llm
    )
    selected_evidence_sku_set = set(evidence_skus_selected_by_llm)
    selected_sku_set = set(selected_skus_for_contract)
    if not raw_selected_evidence_ids:
        # evidence_ids is optional model metadata.  When it is omitted, the
        # selected SKU still remains usable if it exists in this turn's
        # evidence packet; the answer must not be discarded for a missing
        # redundant field.
        evidence_selection_matches = True
    elif semantic_selection_answer:
        # A recommendation/comparison may explain the choice with competing
        # candidates as well as the final selection.
        evidence_selection_matches = bool(selected_evidence_sku_set)
    else:
        # For a product fact, every explicitly cited evidence SKU must belong
        # to the selected set and every selected SKU must be represented by
        # the cited evidence.  This is provenance validation, not a question
        # classifier or a hard-coded field route.
        evidence_selection_matches = (
            bool(selected_evidence_sku_set)
            and selected_evidence_sku_set == selected_sku_set
        )
    raw_selection_state = _normalize_selection_state(
        (answer_raw or {}).get("selection_state"),
        answer_type=raw_answer_type,
        selected_skus=list(selected_skus_for_contract),
    )
    # The model may semantically bind one SKU or several SKUs.  Several are
    # valid for a shared, convergent fact; the only server-side requirement is
    # that the model's explicit provenance points to the same selected set.
    identity_resolution_declared = (
        isinstance((answer_raw or {}).get("identity_resolution"), str)
        and bool(str((answer_raw or {}).get("identity_resolution") or "").strip())
    )
    # ``identity_resolution`` is optional reporting metadata.  If the model
    # supplies the richer selection state and matching evidence, infer the
    # same resolved state for observability; omission alone never rewrites a
    # usable answer.
    inferred_identity_resolution = (
        not identity_resolution_declared
        and raw_selection_state == "selected"
        and bool(selected_skus_for_contract)
        and evidence_selection_matches
    )
    identity_contract_valid = (
        not unanchored_product_detail
        or (
            (raw_identity_resolution == "resolved" or inferred_identity_resolution)
            and bool(selected_skus_for_contract)
            and evidence_selection_matches
        )
    )
    identity_ambiguity = unanchored_product_detail and not identity_contract_valid
    # A single-product fact answer must not cite a different SKU.  A
    # recommendation or comparison is different: its explanation can
    # legitimately cite several candidates while ``selected_skus`` contains
    # only the final recommendation (or a subset of compared products).  The
    # old global check treated that normal multi-product explanation as a
    # provenance conflict and replaced a valid answer with a fixed
    # clarification.
    selection_provenance_conflict = (
        not semantic_selection_answer
        and bool(raw_selected_skus)
        and bool(evidence_skus_selected_by_llm)
        and not set(evidence_skus_selected_by_llm).issubset(raw_selected_skus)
    )
    # A follow-up may resolve a product from the previous conversation packet
    # rather than from this turn's top retrieval rows.  Preserve that semantic
    # evidence selection in the candidate memory/output.  This is provenance
    # propagation, not product-name matching: the SKU can enter this set only
    # when it was explicitly selected from the current evidence packet.  Never
    # propagate a selection that already failed the provenance conflict check.
    semantic_candidate_skus = (
        []
        if selection_provenance_conflict
        else list(selected_skus_for_contract)
    )
    candidate_skus_for_output = list(dict.fromkeys(candidate_skus))
    existing_candidate_set = set(candidate_skus_for_output)
    missing_semantic_candidates = [
        sku for sku in semantic_candidate_skus
        if sku not in existing_candidate_set
    ]
    # Keep retrieval order stable for candidates already on the current page.
    # Context-resolved SKUs that are absent from this turn's retrieval still
    # get a bounded slot, so they cannot disappear merely because a follow-up
    # returned a different top-k page.
    candidate_skus_for_output = [
        *missing_semantic_candidates,
        *candidate_skus_for_output,
    ][: _MAX_CANDIDATE_SKUS]
    validation_raw = answer_raw
    if general_guidance_request and isinstance(validation_raw, dict):
        validation_raw = {
            **validation_raw,
            "selected_skus": [],
        }
    # An evidence id can be the model's only explicit selection for a normal
    # product answer.  Do not promote such an id when the model itself says
    # the turn is only a candidate/no-match explanation; that evidence may be
    # cited to explain why the candidate was not suitable.
    if (
        isinstance(answer_raw, dict)
        and not general_guidance_request
        and not raw_selected_skus
        and evidence_skus_selected_by_llm
        and raw_selection_state not in {"candidate_only", "no_match"}
    ):
        validation_raw = {
            **answer_raw,
            "selected_skus": evidence_skus_selected_by_llm,
        }
    if selection_provenance_conflict and isinstance(answer_raw, dict):
        validation_raw = {
            **answer_raw,
            # Do not expose a model draft that may contain facts from an
            # different SKU.  This is the one hard stop that remains: the
            # model explicitly cited evidence from a SKU outside its own
            # selection.  Missing optional identity metadata is deliberately
            # not treated the same way.
            "answer": "",
            "answer_type": "clarification",
            "needs_clarification": True,
            "selected_skus": [],
            "evidence_ids": [],
        }
    (
        answer,
        answer_type,
        needs_clarification,
        confidence,
        uncertainty,
        result_skus,
        selected_evidence_ids,
        followups,
    ) = _validated_workbuddy_answer(
        validation_raw,
        evidence=evidence,
        candidate_skus=candidate_skus,
        identity_ambiguity=identity_ambiguity,
    )
    # The model's state is useful for diagnosis, but the public state must
    # describe the normalized result.  A model can say ``selected`` while
    # returning a clarification; in that case the selected SKU has already
    # been discarded by the provenance boundary and must not remain visible
    # as a confirmed selection in debug metadata.
    effective_selection_state = raw_selection_state
    if answer_type == "clarification":
        # A clarification can mean two different semantic outcomes: the
        # model may have recalled possible products but not selected one, or
        # it may have explicitly concluded that none of the recalled products
        # satisfies the request.  Preserve that model-owned distinction when
        # it is present; only fill a missing/invalid state from the available
        # candidate set.  The previous unconditional rewrite made a semantic
        # no-match look like an available candidate in the UI and trace.
        if raw_selection_state not in {"candidate_only", "no_match"}:
            effective_selection_state = "candidate_only" if candidate_skus else "no_match"
    elif answer_type in {"recommendation", "comparison"} and not result_skus:
        effective_selection_state = "candidate_only" if candidate_skus else "no_match"
    # The model's explicit ``selection_state=selected`` plus a single selected
    # SKU whose evidence matches is already the semantic identity decision.
    # ``identity_resolution`` is an optional, redundant reporting field; do
    # not expose ``unresolved`` to callers when the answer contract was valid
    # merely because the model omitted that duplicate field.  Keep the raw
    # value separately for trace/debug inspection.
    effective_identity_resolution = raw_identity_resolution
    if inferred_identity_resolution:
        effective_identity_resolution = "resolved"
    working_memory_update = _normalize_working_memory_update(
        (answer_raw or {}).get("working_memory_update")
        if isinstance(answer_raw, dict)
        else None,
        result_skus=result_skus,
        candidate_skus=candidate_skus_for_output,
    )
    # Candidate recall is not a semantic product selection.  In particular,
    # a product QA question with several possible matches must remain a pure
    # clarification: exposing the whole recall page as result_skus makes the
    # UI and the next turn look as if those products were selected.  The
    # candidates remain available in candidate_skus/evidence for the model and
    # for the customer to disambiguate.

    state = customer_perf_service.get_state() or {}
    answer_metadata = {
        "pipeline_version": PIPELINE_VERSION,
        "semantic_owner": "workbuddy_answer_llm",
        "evidence_status": "matched" if evidence else "missing",
        "evidence_ids": selected_evidence_ids,
        "evidence_skus": sorted({
            str(item.get("sku") or "").strip().upper()
            for item in evidence
            if str(item.get("sku") or "").strip()
        }),
        "identity_resolution": effective_identity_resolution,
        "model_identity_resolution": raw_identity_resolution,
        "identity_contract_valid": identity_contract_valid,
        "subject_scope": raw_subject_scope or ("product_specific" if product_scoped_request else ""),
        "selection_state": effective_selection_state,
        "model_selection_state": raw_selection_state,
        "retrieval_mode": "semantic_rag_single_pass",
        "llm_call_count": len(state.get("llm_calls") or []),
        "answer_llm_elapsed_ms": answer_metadata.get("elapsed_ms"),
        "working_memory_update": working_memory_update,
        "plan_available": False,
        "experience_guidance_count": len(experience_guidance),
        "experience_guidance_ids": customer_experience_rag_service.guidance_ids(experience_guidance),
        **answer_metadata,
    }
    plan = _pipeline_plan(
        answer_raw,
        question=original_question,
        queries=queries,
        known_skus=known_skus,
        candidate_skus=candidate_skus_for_output,
    )
    debug = {
        "pipeline_version": PIPELINE_VERSION,
        "agent_mode": PIPELINE_VERSION,
        "no_legacy_route": True,
        "semantic_owner": "llm",
        "plan": plan,
        "plan_metadata": {"mode": "single_answer_llm", "raw_valid": bool(answer_raw)},
        "target_skus": known_skus,
        "catalogue_subject_skus": catalogue_subject_skus,
        "retrieval_scope_skus": retrieval_scope_skus,
        "anchor_skus": anchor_skus,
        "active_context_skus": active_context_skus,
        "candidate_skus": candidate_skus_for_output,
        "retrieved_candidate_skus": candidate_skus,
        "semantic_candidate_skus": semantic_candidate_skus,
        "evidence_ids": [item.get("evidence_id") for item in evidence],
        "selected_evidence_ids": selected_evidence_ids,
        "identity_ambiguity": identity_ambiguity,
        "identity_resolution": effective_identity_resolution,
        "model_identity_resolution": raw_identity_resolution,
        "identity_contract_valid": identity_contract_valid,
        "subject_scope": raw_subject_scope or ("product_specific" if product_scoped_request else ""),
        "selection_state": effective_selection_state,
        "model_selection_state": raw_selection_state,
        "selection_provenance_conflict": selection_provenance_conflict,
        "model_selected_skus": sorted(raw_selected_skus),
        "model_selected_evidence_ids": list(raw_selected_evidence_ids)[:12],
        "model_evidence_skus": evidence_skus_selected_by_llm,
        "experience_guidance_count": len(experience_guidance),
        "experience_guidance_ids": customer_experience_rag_service.guidance_ids(experience_guidance),
        "llm_call_count": len(state.get("llm_calls") or []),
        "elapsed_before_persist_ms": round(customer_perf_service.perf_ms(request_start), 2),
    }
    sources = [
        {
            "type": "rag_evidence",
            "source_type": item.get("source_type"),
            "source_id": item.get("source_id"),
            "sku": item.get("sku"),
            "content": item.get("content"),
            "score": item.get("score"),
            "evidence_id": item.get("evidence_id"),
        }
        for item in evidence
    ]
    agent_result = {
        "answer": answer,
        "answer_type": answer_type,
        "intent": {
            "recommendation": "recommendation",
            "comparison": "compare_products",
            "product_detail": "product_detail",
            "faq": "customer_faq",
            "clarification": "clarify",
        }.get(answer_type, "customer_faq"),
        "needs_clarification": needs_clarification,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "result_skus": result_skus,
        "candidate_skus": candidate_skus_for_output,
        "evidence": evidence,
        "sources": sources,
        "steps": [
            {"type": "semantic_understanding", "label": "理解当前问题和上下文", "ok": True},
            {"type": "semantic_retrieve", "label": "检索商品资料和知识库", "ok": bool(evidence)},
            {"type": "same_sku_evidence", "label": "绑定商品事实来源", "ok": bool(allowed_skus) or not evidence},
            {"type": "workbuddy_answer", "label": "生成自然客服回复", "ok": bool(answer_raw)},
        ],
        "suggested_followups": followups,
        "followups": followups,
        "answer_metadata": answer_metadata,
        "debug": debug,
        # Candidate recall is not the same thing as an answer selection.  The
        # previous implementation exposed every recalled product here, even
        # when the LLM had selected only a subset for the answer.  That made
        # the UI look like the service recommended unrelated products.  Cards
        # follow the semantic result selection and remain empty when the
        # answer did not select a product; the full candidate set stays in the
        # debug/evidence fields for audit and later turns.
        "results": [
            product_details[item]
            for item in result_skus
            if item in product_details
        ] if answer_type in {"recommendation", "comparison"} else (
            [] if identity_ambiguity else [
                product_details[item]
                for item in result_skus[:_MAX_PROMPT_CANDIDATE_PRODUCTS]
                if item in product_details
            ]
        ),
        "skip_polish": True,
    }
    return await _persist_result(
        db,
        user_id=str(user_id),
        question=original_question,
        conversation_id=conversation_id,
        agent_result=agent_result,
        answer_delta_callback=answer_delta_callback,
        answer_already_streamed=bool(answer_metadata.get("answer_streamed")),
    )


async def _persist_result(
    db: Session,
    *,
    user_id: str,
    question: str,
    conversation_id: str | None,
    agent_result: dict[str, Any],
    answer_delta_callback: Callable[[str], Awaitable[None]] | None,
    answer_already_streamed: bool = False,
) -> dict[str, Any]:
    """Persist using the shared conversation contract, scoped to this path."""
    from . import customer_service_service as shared_service

    persist_start = perf_counter()
    result_skus = [
        str(item or "").strip().upper()
        for item in (agent_result.get("result_skus") or [])
        if str(item or "").strip()
    ]
    conversation = shared_service._get_or_create_conversation(
        db,
        str(user_id),
        question,
        result_skus[0] if len(result_skus) == 1 else None,
        conversation_id,
        pipeline=PIPELINE_VERSION,
    )
    db.add(CustomerServiceMessage(
        conversation_id=conversation.id,
        role="user",
        content=question,
        sku=result_skus[0] if len(result_skus) == 1 else None,
    ))
    turn_index = shared_service._assistant_turn_index(db, conversation.id)
    sources_with_context = shared_service._sources_with_result_context(
        agent_result,
        turn_index=turn_index,
        user_question=question,
        inherited_recommendation_context=shared_service._latest_recommendation_context_for_sources(db, conversation.id),
        inherited_candidate_context=shared_service._latest_candidate_context_for_sources(db, conversation.id),
    )
    assistant_message = CustomerServiceMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=str(agent_result.get("answer") or ""),
        sku=result_skus[0] if len(result_skus) == 1 else None,
        sources_json=json.dumps(sources_with_context, ensure_ascii=False, default=str),
    )
    db.add(assistant_message)
    shared_service._touch_conversation(
        conversation,
        result_skus[0] if len(result_skus) == 1 else None,
    )
    db.flush()
    db.commit()
    customer_perf_service.log_stage(
        "customer_service_workbuddy.persist",
        persist_start,
        branch=PIPELINE_VERSION,
    )
    persist_elapsed_ms = round(customer_perf_service.perf_ms(persist_start), 2)
    public = _public_result(
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        answer=str(agent_result.get("answer") or ""),
        answer_type=str(agent_result.get("answer_type") or "clarification"),
        needs_clarification=bool(agent_result.get("needs_clarification")),
        confidence=str(agent_result.get("confidence") or "low"),
        uncertainty=str(agent_result.get("uncertainty") or "unconfirmed"),
        result_skus=result_skus,
        candidate_skus=[
            str(item or "").strip().upper()
            for item in (agent_result.get("candidate_skus") or [])
            if str(item or "").strip()
        ],
        evidence=list(agent_result.get("evidence") or []),
        selected_evidence_ids=list((agent_result.get("answer_metadata") or {}).get("evidence_ids") or []),
        sources=sources_with_context,
        steps=list(agent_result.get("steps") or []),
        followups=list(agent_result.get("suggested_followups") or []),
        plan=((agent_result.get("debug") or {}).get("plan") or {}),
        plan_metadata=((agent_result.get("debug") or {}).get("plan_metadata") or {}),
        answer_metadata=dict(agent_result.get("answer_metadata") or {}),
        debug=dict(agent_result.get("debug") or {}),
        results=list(agent_result.get("results") or []),
        pipeline_version=PIPELINE_VERSION,
        intent_override=str(agent_result.get("intent") or "").strip() or None,
        anomalies=list(agent_result.get("anomalies") or []),
        warnings=list(agent_result.get("warnings") or []),
        actions=list(agent_result.get("actions") or []),
    )
    public_debug = dict(public.get("debug") or {})
    public["skip_polish"] = True
    public_debug["skip_polish"] = True
    public_debug["persist_elapsed_ms"] = persist_elapsed_ms
    public["debug"] = public_debug
    public_metadata = dict(public.get("answer_metadata") or {})
    public_metadata["persist_elapsed_ms"] = persist_elapsed_ms
    public["answer_metadata"] = public_metadata
    if answer_delta_callback is not None and not answer_already_streamed:
        try:
            await answer_delta_callback(public["answer"])
        except Exception:
            customer_perf_service.log_event("customer_service_workbuddy.stream_callback_error")
    return public
