import asyncio
import json
import logging
from time import perf_counter

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..core.database import get_db, release_session_connection
from ..core.rate_limit import enforce_rate_limit
from ..core.security import get_user_permissions, require_permission
from ..models.knowledge_base import CustomerServiceConversation, CustomerServiceMessage
from ..models.user import User
from ..services import agent_action_service, customer_perf_service, customer_service_service, operation_log_service

router = APIRouter(prefix="/api/customer-service", tags=["customer-service"])
logger = logging.getLogger("uvicorn")


class CustomerServiceAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    sku: str | None = Field(default=None, max_length=100)
    conversation_id: str | None = Field(default=None, max_length=100)


class CustomerServiceFeedbackRequest(BaseModel):
    rating: str = Field(..., min_length=1, max_length=30)
    reason: str | None = Field(default=None, max_length=100)
    comment: str | None = Field(default=None, max_length=1000)


@router.get("/conversations")
def list_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    return customer_service_service.list_conversations(db, current_user.id, skip, limit)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    return customer_service_service.get_conversation(db, conversation_id, current_user.id)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    return customer_service_service.delete_conversation(db, conversation_id, current_user.id)


@router.post("/messages/{message_id}/feedback")
def save_feedback(
    message_id: str,
    body: CustomerServiceFeedbackRequest,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    return customer_service_service.save_message_feedback(
        db,
        user_id=current_user.id,
        message_id=message_id,
        rating=body.rating,
        reason=body.reason,
        comment=body.comment,
    )


@router.get("/review-samples")
def review_samples(
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    return customer_service_service.review_samples(db, current_user.id, limit)


@router.post("/actions/{action_id}/confirm")
def confirm_action(
    action_id: str,
    request: Request,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    permissions = set(get_user_permissions(db, current_user.id))
    return agent_action_service.confirm_action(
        db,
        action_id=action_id,
        confirmed_by=current_user.id,
        permissions=permissions,
        request=request,
    )


@router.post("/actions/{action_id}/cancel")
def cancel_action(
    action_id: str,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    return agent_action_service.cancel_action(db, action_id, cancelled_by=current_user.id)


@router.post("/ask")
async def ask(
    body: CustomerServiceAskRequest,
    request: Request,
    debug: bool = Query(False),
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    customer_perf_service.start_trace()
    request_start = perf_counter()
    precheck_start = perf_counter()
    enforce_rate_limit(user_id=current_user.id, scope="customer_service.ask", limit=60, window_seconds=60)
    customer_perf_service.log_stage("ask_api.precheck", precheck_start, permission_checked=True, rate_limit_checked=True)
    service_start = perf_counter()
    result = await customer_service_service.ask_customer_service(
        db,
        user_id=current_user.id,
        question=body.question,
        sku=body.sku,
        conversation_id=body.conversation_id,
    )
    customer_perf_service.log_stage(
        "ask_api.service_call",
        service_start,
        conversation_id=result.get("conversation_id"),
        intent=result.get("intent"),
        agent_mode=(result.get("debug") or {}).get("agent_mode"),
    )
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="ask",
        action_name="智能客服问答",
        target_type="customer_service",
        target_id=result["conversation_id"],
        target_name=result.get("sku") or "未选择产品",
        request_data={"question": body.question, "sku": body.sku},
        response_data={"answer": result["answer"], "sources": result["sources"]},
        request=request,
    )
    customer_perf_service.log_stage("ask_api.total", request_start, conversation_id=result.get("conversation_id"), intent=result.get("intent"))
    perf_summary = customer_perf_service.summarize_request(final_answer=result.get("answer"), intent=result.get("intent"), agent_mode=(result.get("debug") or {}).get("agent_mode"))
    if debug or str(request.headers.get("X-Debug-Trace") or "").lower() in {"1", "true", "yes"}:
        _attach_debug_trace(result, perf_summary)
    return result


@router.post("/ask-stream")
async def ask_stream(
    body: CustomerServiceAskRequest,
    request: Request,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    customer_perf_service.start_trace()
    request_start = perf_counter()
    precheck_start = perf_counter()
    enforce_rate_limit(user_id=current_user.id, scope="customer_service.ask_stream", limit=60, window_seconds=60)
    customer_perf_service.log_stage("ask_stream.precheck", precheck_start, permission_checked=True, rate_limit_checked=True)
    async def event_stream():
        try:
            yield _sse("status", {"message": "agent_planning", "label": "正在理解问题并选择工具"})
            planned_start = perf_counter()
            delta_queue: asyncio.Queue[str] = asyncio.Queue()
            first_delta_logged = False

            async def on_answer_delta(text: str) -> None:
                await delta_queue.put(text)

            service_task = asyncio.create_task(customer_service_service.ask_customer_service(
                db,
                user_id=current_user.id,
                question=body.question,
                sku=body.sku,
                conversation_id=body.conversation_id,
                answer_delta_callback=on_answer_delta,
            ))
            while not service_task.done() or not delta_queue.empty():
                try:
                    delta = await asyncio.wait_for(delta_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if not first_delta_logged:
                    customer_perf_service.mark_first_answer_delta()
                    first_delta_logged = True
                yield _sse("content", {"type": "content", "content": delta})
            result = await service_task
            customer_perf_service.log_stage(
                "ask_stream.service_call",
                planned_start,
                conversation_id=result.get("conversation_id"),
                intent=result.get("intent"),
                agent_mode=(result.get("debug") or {}).get("agent_mode"),
            )
            yield _sse("status", {"message": "agent_reasoning", "label": "正在基于资料推理回复"})
            operation_log_service.log_operation(
                db,
                operator_id=current_user.id,
                action_type="ask",
                action_name="智能客服问答",
                target_type="customer_service",
                target_id=result["conversation_id"],
                target_name=result.get("sku") or "未选择产品",
                request_data={"question": body.question, "sku": body.sku},
                response_data={"answer": result["answer"], "sources": result["sources"]},
                request=request,
            )
            release_session_connection(db)
            trace_payload = _build_trace_payload(db, result, body.question, current_user.id)
            release_session_connection(db)
            yield _sse("meta", {
                "conversation_id": result["conversation_id"],
                "message_id": result.get("message_id"),
                "intent": result.get("intent"),
                "answer_type": result.get("answer_type"),
                "confidence": result.get("confidence"),
                "uncertainty": result.get("uncertainty"),
                "needs_clarification": result.get("needs_clarification", False),
                "anomalies": result.get("anomalies") or [],
                "suggested_followups": result.get("suggested_followups") or [],
                "followups": result.get("followups") or result.get("suggested_followups") or [],
                "warnings": result.get("warnings") or [],
                "evidence": result.get("evidence") or [],
                "agent_quality": result.get("agent_quality") or {},
                "answer_metadata": result.get("answer_metadata") or {},
                "debug": result.get("debug") or {},
                "sku": result.get("sku"),
                "sources": result.get("sources") or [],
                "actions": result.get("actions") or [],
                "results": result.get("results") or [],
                "steps": result.get("steps") or [],
            })
            if result.get("needs_clarification"):
                yield _sse("clarification", {
                    "message": result.get("answer"),
                    "suggested_followups": result.get("suggested_followups") or [],
                })
            for warning in result.get("warnings") or []:
                yield _sse("warning", {"message": warning})
            for recommendation in (result.get("suggested_followups") or [])[:2]:
                yield _sse("recommendation", {"message": recommendation})
            if not first_delta_logged:
                for chunk in _chunk_text(result.get("answer") or ""):
                    if not first_delta_logged:
                        customer_perf_service.mark_first_answer_delta()
                        first_delta_logged = True
                    yield _sse("answer_delta", {"text": chunk})
                    await asyncio.sleep(0.01)
            customer_perf_service.mark_done()
            yield _sse("done", {"ok": True})
            yield _sse("trace", trace_payload)
            customer_perf_service.log_stage("ask_stream.total", request_start, conversation_id=result.get("conversation_id"), intent=result.get("intent"))
            customer_perf_service.summarize_request(final_answer=result.get("answer"), intent=result.get("intent"), agent_mode=(result.get("debug") or {}).get("agent_mode"))
        except Exception:
            logger.exception("customer service stream failed")
            yield _sse("error", {"message": _public_error_message()})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _attach_debug_trace(result: dict, perf_summary: dict | None) -> None:
    if not isinstance(result, dict):
        return
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    metadata = result.get("answer_metadata") if isinstance(result.get("answer_metadata"), dict) else {}
    final_decision = metadata.get("final_decision") if isinstance(metadata.get("final_decision"), dict) else {}
    summary_extra = (perf_summary or {}).get("extra") if isinstance(perf_summary, dict) else {}
    if not isinstance(summary_extra, dict):
        summary_extra = {}
    llm_calls = summary_extra.get("llm_calls") if isinstance(summary_extra.get("llm_calls"), list) else []
    stages = summary_extra.get("stages") if isinstance(summary_extra.get("stages"), list) else []

    routing_stage = ""
    fallback_stage = ""
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_name = str(stage.get("stage") or "")
        if not routing_stage and (
            "fast_path" in stage_name
            or stage_name in {"named_product_shortcut", "process_intent_request_pre_runtime", "process_agent_request"}
        ):
            routing_stage = stage_name
        if not fallback_stage and "fallback" in stage_name:
            fallback_stage = stage_name

    debug_trace = {
        "trace_id": (perf_summary or {}).get("trace_id") or customer_perf_service.get_trace_id() or "",
        "intent": result.get("intent") or "",
        "agent_mode": result.get("agent_mode") or debug.get("agent_mode") or "",
        "answer_type": result.get("answer_type") or "",
        "final_decision": final_decision,
        "llm_call_count": int(summary_extra.get("llm_call_count") or 0),
        "llm_calls": llm_calls,
        "skip_polish": bool(debug.get("skip_polish") or result.get("skip_polish") or final_decision.get("llm_allowed") is False),
        "primary_source": final_decision.get("primary_source") or "",
        "routing_stage": routing_stage,
        "fallback_stage": fallback_stage,
        "stages": stages,
    }
    debug["trace"] = debug_trace
    debug["trace_id"] = debug_trace["trace_id"]
    debug["llm_call_count"] = debug_trace["llm_call_count"]
    debug["llm_calls"] = llm_calls
    result["debug"] = debug
    metadata["debug"] = debug_trace
    metadata["trace_id"] = debug_trace["trace_id"]
    metadata["llm_call_count"] = debug_trace["llm_call_count"]
    metadata["llm_calls"] = llm_calls
    result["answer_metadata"] = metadata


def _build_trace_payload(db: Session, result: dict, question: str, user_id: str) -> dict:
    state = customer_perf_service.get_state() or {}
    stages = state.get("stages") or []
    llm_calls = state.get("llm_calls") or []
    debug = result.get("debug") or {}
    previous_excluded = _trace_previous_recommended_skus_excluded(
        db,
        question=question,
        conversation_id=result.get("conversation_id"),
        user_id=str(user_id),
    )

    return {
        "trace_id": customer_perf_service.get_trace_id() or state.get("trace_id") or "",
        "conversation_id": result.get("conversation_id") or "",
        "agent_mode": _trace_agent_mode(result, stages),
        "intent": result.get("intent") or debug.get("intent") or "",
        "usage_care_subtype": debug.get("usage_care_subtype"),
        "result_skus": _trace_result_skus(result),
        "llm_call_count": len(llm_calls),
        "prompt_chars": sum(int(call.get("prompt_chars") or 0) for call in llm_calls),
        "total_ms": round(float(state.get("done_at") or debug.get("total_ms") or 0), 2),
        "first_token_ms": round(float(state.get("first_answer_delta_at") or debug.get("total_ms") or 0), 2),
        "product_qa_ms": debug.get("product_qa_ms"),
        "knowledge_search_ms": debug.get("knowledge_search_ms"),
        "rerank_ms": debug.get("rerank_ms"),
        "compose_answer_ms": debug.get("compose_answer_ms"),
        "product_qa_count": debug.get("qa_result_count"),
        "knowledge_chunk_count": debug.get("knowledge_result_count"),
        "final_used_sources_count": debug.get("final_used_sources_count"),
        "filtered_or_downgraded": debug.get("filtered_or_downgraded") or [],
        "hit_faq_fast_path": _trace_stage_hit(stages, "customer_faq_fast_path"),
        "entered_process_agent_request": _trace_stage_seen(stages, "process_agent_request"),
        "entered_process_intent_fallback": _trace_stage_seen(stages, "process_intent_request_fallback"),
        "entered_semantic_retrieve": _trace_semantic_retrieve_seen(stages, result),
        "entered_hybrid_search": _trace_hybrid_search_seen(stages, result),
        "recommendation_context_found": _trace_recommendation_context_found(result),
        "previous_recommended_skus_excluded": previous_excluded,
    }


def _trace_agent_mode(result: dict, stages: list[dict]) -> str:
    raw_mode = str(result.get("agent_mode") or (result.get("debug") or {}).get("agent_mode") or "")
    if _trace_stage_hit(stages, "customer_faq_fast_path") or "faq_fast_path" in raw_mode or "purchase_channel_fast_path" in raw_mode:
        return "faq_fast"
    if _trace_stage_seen(stages, "process_intent_request_fallback"):
        return "intent_fallback"
    if raw_mode.startswith("deterministic_") or raw_mode in {"named_product_shortcut", "single_sku_knowledge"}:
        return "field_direct"
    return "agent"


def _trace_stage_seen(stages: list[dict], stage_name: str) -> bool:
    return any(item.get("stage") == stage_name for item in stages)


def _trace_stage_hit(stages: list[dict], stage_name: str) -> bool:
    for item in stages:
        if item.get("stage") == stage_name:
            extra = item.get("extra") or {}
            if extra.get("hit") is True:
                return True
    return False


def _trace_semantic_retrieve_seen(stages: list[dict], result: dict) -> bool:
    if any("semantic_retrieve" in str(item.get("stage") or "") for item in stages):
        return True
    return _trace_contains_tool(result, {"semantic_search_knowledge"})


def _trace_hybrid_search_seen(stages: list[dict], result: dict) -> bool:
    if any("hybrid_search" in str(item.get("stage") or "") for item in stages):
        return True
    return _trace_contains_tool(result, {"hybrid_search_products"})


def _trace_contains_tool(result: dict, tool_names: set[str]) -> bool:
    stack = [
        result.get("sources") or [],
        result.get("steps") or [],
        (result.get("debug") or {}).get("tool_results") or [],
        (result.get("debug") or {}).get("steps") or [],
    ]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            values = {str(item.get(key) or "") for key in ("tool", "type", "name")}
            if values & tool_names:
                return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


def _trace_result_skus(result: dict) -> list[str]:
    skus: list[str] = []

    def add(raw: object) -> None:
        sku = str(raw or "").strip().upper()
        if sku and "," not in sku and sku not in skus:
            skus.append(sku)

    for sku in result.get("result_skus") or []:
        add(sku)
    for row in result.get("results") or []:
        if isinstance(row, dict):
            add(row.get("sku"))
    for source in result.get("sources") or []:
        if not isinstance(source, dict):
            continue
        for sku in source.get("result_skus") or []:
            add(sku)
        for row in source.get("results") or []:
            if isinstance(row, dict):
                add(row.get("sku"))
    if result.get("sku"):
        add(result.get("sku"))
    return skus


def _trace_recommendation_context_found(result: dict) -> bool:
    if result.get("intent") == "recommend_products" and _trace_result_skus(result):
        return True
    for source in result.get("sources") or []:
        if isinstance(source, dict) and source.get("recommendation_context"):
            return True
    return False


def _trace_previous_recommended_skus_excluded(
    db: Session,
    *,
    question: str,
    conversation_id: str | None,
    user_id: str,
) -> list[str]:
    if not conversation_id or not _trace_asks_to_exclude_previous(question):
        return []
    conversation = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.id == conversation_id,
        CustomerServiceConversation.user_id == user_id,
    ).first()
    if not conversation:
        return []
    messages = (
        db.query(CustomerServiceMessage)
        .filter(
            CustomerServiceMessage.conversation_id == conversation.id,
            CustomerServiceMessage.role == "assistant",
        )
        .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
        .limit(5)
        .all()
    )
    for message in messages[1:]:
        skus = _trace_recommended_skus_from_sources(message.sources_json)
        if skus:
            return skus
    return []


def _trace_asks_to_exclude_previous(question: str) -> bool:
    text = str(question or "")
    return any(term in text for term in ("换一个", "换一款", "换个", "不要刚才", "别要刚才", "另外推荐", "其他推荐"))


def _trace_recommended_skus_from_sources(sources_json: str | None) -> list[str]:
    try:
        sources = json.loads(sources_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(sources, list):
        return []
    for source in sources:
        if isinstance(source, dict) and isinstance(source.get("recommendation_context"), dict):
            return [
                str(sku).strip().upper()
                for sku in source["recommendation_context"].get("recommended_skus") or []
                if str(sku or "").strip()
            ]
    for source in sources:
        if isinstance(source, dict) and source.get("type") == "agent_context":
            return [
                str(sku).strip().upper()
                for sku in source.get("result_skus") or []
                if str(sku or "").strip()
            ]
    return []


def _public_error_message() -> str:
    return "智能客服暂时不可用，请稍后重试"


def _chunk_text(text: str, size: int = 3):
    for index in range(0, len(text), size):
        yield text[index:index + size]
