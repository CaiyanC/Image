import json
import re
from time import perf_counter
from typing import Awaitable, Callable

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..core.database import release_session_connection
from ..models.knowledge_base import CustomerServiceConversation, CustomerServiceMessage
from ..models.product import Product
from ..models.product_qa import ProductQa, ProductQaNegative
from . import (
    customer_enterprise_guardrail_service,
    customer_agent_intent_service,
    customer_agent_quality_service,
    customer_agent_runtime_service,
    customer_agent_service,
    customer_cache_service,
    customer_dialogue_state,
    customer_llm_service,
    customer_perf_service,
    knowledge_service,
    product_service,
)


SKU_RE = re.compile(r"\b[A-Za-z]{1,6}[-_][A-Za-z0-9][A-Za-z0-9_-]{1,40}\b")


def list_conversations(db: Session, user_id: str, skip: int = 0, limit: int = 30) -> dict:
    user_id = str(user_id)
    query = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.user_id == user_id
    ).order_by(CustomerServiceConversation.updated_at.desc())
    total = query.count()
    items = query.offset(skip).limit(limit).all()
    previews = _conversation_previews(db, [item.id for item in items])
    return {
        "items": [_conversation_list_item(item, previews.get(item.id, {})) for item in items],
        "total": total,
    }


def _conversation_previews(db: Session, conversation_ids: list[str]) -> dict[str, dict]:
    if not conversation_ids:
        return {}
    previews: dict[str, dict] = {conversation_id: {} for conversation_id in conversation_ids}
    rows = (
        db.query(CustomerServiceMessage)
        .filter(CustomerServiceMessage.conversation_id.in_(conversation_ids))
        .order_by(CustomerServiceMessage.conversation_id.asc(), CustomerServiceMessage.created_at.desc())
        .all()
    )
    for message in rows:
        preview = previews.setdefault(message.conversation_id, {})
        preview.setdefault("last_any", message)
        if message.role == "assistant":
            preview.setdefault("last_assistant", message)
    return previews


def _conversation_list_item(item: CustomerServiceConversation, preview: dict) -> dict:
    preview_message = preview.get("last_assistant") or preview.get("last_any")
    preview = str(preview_message.content or "") if preview_message else ""
    return {
        "id": item.id,
        "title": item.title,
        "sku": item.sku,
        "last_message": preview[:120],
        "last_message_role": preview_message.role if preview_message else None,
        "last_message_at": str(preview_message.created_at) if preview_message and preview_message.created_at else None,
        "created_at": str(item.created_at),
        "updated_at": str(item.updated_at),
    }


def get_conversation(db: Session, conversation_id: str, user_id: str) -> dict:
    user_id = str(user_id)
    conversation = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.id == conversation_id,
        CustomerServiceConversation.user_id == user_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客服会话不存在")

    messages = db.query(CustomerServiceMessage).filter(
        CustomerServiceMessage.conversation_id == conversation_id
    ).order_by(CustomerServiceMessage.created_at.asc()).all()
    payload = []
    for item in messages:
        meta = _message_meta(item.sources_json)
        payload.append(
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "sku": item.sku,
                "sources": _safe_json(item.sources_json, []),
                "steps": _steps_from_sources(item.sources_json),
                "intent": meta.get("intent"),
                "answer_type": meta.get("answer_type"),
                "confidence": meta.get("confidence"),
                "uncertainty": meta.get("uncertainty"),
                "needs_clarification": meta.get("needs_clarification", False),
                "anomalies": meta.get("anomalies", []),
                "suggested_followups": meta.get("suggested_followups", meta.get("followups", [])),
                "followups": meta.get("followups", meta.get("suggested_followups", [])),
                "warnings": meta.get("warnings", []),
                "evidence": meta.get("evidence", []),
                "agent_quality": meta.get("agent_quality", {}),
                "debug": meta.get("debug", {}),
                "feedback": meta.get("feedback"),
                "created_at": str(item.created_at),
            }
        )
    return {
        "id": conversation.id,
        "title": conversation.title,
        "sku": conversation.sku,
        "created_at": str(conversation.created_at),
        "updated_at": str(conversation.updated_at),
        "messages": payload,
    }


def delete_conversation(db: Session, conversation_id: str, user_id: str) -> dict:
    user_id = str(user_id)
    conversation = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.id == conversation_id,
        CustomerServiceConversation.user_id == user_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客服会话不存在")
    db.delete(conversation)
    db.commit()
    return {"deleted": True, "id": conversation_id}


def save_message_feedback(
    db: Session,
    *,
    user_id: str,
    message_id: str,
    rating: str,
    reason: str | None = None,
    comment: str | None = None,
) -> dict:
    allowed = {"helpful", "incorrect", "missing_data"}
    if rating not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="反馈类型不支持")
    message = (
        db.query(CustomerServiceMessage)
        .join(CustomerServiceConversation, CustomerServiceConversation.id == CustomerServiceMessage.conversation_id)
        .filter(
            CustomerServiceMessage.id == message_id,
            CustomerServiceMessage.role == "assistant",
            CustomerServiceConversation.user_id == str(user_id),
        )
        .first()
    )
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客服消息不存在")

    sources = _safe_json(message.sources_json, [])
    meta = None
    for source in sources:
        if isinstance(source, dict) and source.get("type") == "agent_meta":
            meta = source
            break
    if meta is None:
        meta = {"type": "agent_meta", "label": "客服回复元数据"}
        sources.append(meta)
    feedback = {
        "rating": rating,
        "reason": reason or "",
        "comment": comment or "",
    }
    meta["feedback"] = feedback
    message.sources_json = json.dumps(sources, ensure_ascii=False, default=str)
    db.commit()
    return {"message_id": message.id, "feedback": feedback}


async def ask_customer_service(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None = None,
    conversation_id: str | None = None,
    answer_delta_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    user_id = str(user_id)
    question = question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="问题不能为空")
    if not customer_perf_service.get_trace_id():
        customer_perf_service.start_trace()
    request_start = perf_counter()

    named_products = _products_named_in_question(db, question)
    faq_start = perf_counter()
    faq_intent = None if named_products else _classify_customer_faq_intent(question)
    faq_result = None
    if faq_intent:
        faq_result = await _answer_customer_faq_fast_path(db, question, faq_intent)
    customer_perf_service.log_stage(
        "customer_faq_fast_path",
        faq_start,
        hit=bool(faq_result),
        intent=faq_intent,
        agent_mode=(faq_result.get("debug") or {}).get("agent_mode") if faq_result else None,
    )
    if faq_result:
        stage_start = perf_counter()
        conversation = _get_or_create_conversation(db, user_id, question, faq_result.get("sku"), conversation_id)
        db.add(CustomerServiceMessage(
            conversation_id=conversation.id,
            role="user",
            content=question,
            sku=faq_result.get("sku"),
        ))
        assistant_turn_index = _assistant_turn_index(db, conversation.id)
        sources_with_context = _sources_with_result_context(
            faq_result,
            turn_index=assistant_turn_index,
            user_question=question,
        )
        assistant_message = CustomerServiceMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=faq_result["answer"],
            sku=faq_result.get("sku"),
            sources_json=json.dumps(sources_with_context, ensure_ascii=False, default=str),
        )
        db.add(assistant_message)
        _touch_conversation(conversation, faq_result.get("sku"))
        conversation_id_value = conversation.id
        message_id_value = assistant_message.id
        db.commit()
        customer_perf_service.log_stage("save_messages_and_commit", stage_start, branch="faq_fast_path", intent=faq_result.get("intent"))
        customer_perf_service.log_stage("ask_customer_service.total", request_start, branch="faq_fast_path", intent=faq_result.get("intent"), agent_mode=(faq_result.get("debug") or {}).get("agent_mode"))
        customer_perf_service.summarize_request(
            final_answer=faq_result.get("answer"),
            intent=faq_result.get("intent"),
            agent_mode=(faq_result.get("debug") or {}).get("agent_mode"),
        )
        release_session_connection(db)
        return {
            "conversation_id": conversation_id_value,
            "message_id": message_id_value,
            "intent": faq_result.get("intent"),
            "answer_type": faq_result.get("answer_type"),
            "confidence": faq_result.get("confidence"),
            "uncertainty": faq_result.get("uncertainty"),
            "needs_clarification": faq_result.get("needs_clarification", False),
            "anomalies": faq_result.get("anomalies") or [],
            "suggested_followups": faq_result.get("suggested_followups") or [],
            "followups": faq_result.get("followups") or faq_result.get("suggested_followups") or [],
            "warnings": faq_result.get("warnings") or [],
            "evidence": faq_result.get("evidence") or [],
            "agent_quality": faq_result.get("agent_quality") or {},
            "debug": faq_result.get("debug") or {},
            "sku": faq_result.get("sku"),
            "answer": faq_result["answer"],
            "sources": sources_with_context,
            "actions": faq_result.get("actions") or [],
            "results": faq_result.get("results") or [],
            "steps": faq_result.get("steps") or [],
            "result_skus": faq_result.get("result_skus") or [],
            "agent_mode": (faq_result.get("debug") or {}).get("agent_mode"),
        }

    stage_start = perf_counter()
    agent_result = customer_enterprise_guardrail_service.evaluate_question(question)
    customer_perf_service.log_stage("guardrail.evaluate_question", stage_start, matched=bool(agent_result))
    if agent_result:
        stage_start = perf_counter()
        agent_result = _normalize_agent_result(agent_result)
        agent_result = _attach_agent_quality(agent_result, question)
        conversation = _get_or_create_conversation(db, user_id, question, agent_result.get("sku"), conversation_id)
        db.add(CustomerServiceMessage(
            conversation_id=conversation.id,
            role="user",
            content=question,
            sku=agent_result.get("sku"),
        ))
        assistant_turn_index = _assistant_turn_index(db, conversation.id)
        sources_with_context = _sources_with_result_context(
            agent_result,
            turn_index=assistant_turn_index,
            user_question=question,
        )
        assistant_message = CustomerServiceMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=agent_result["answer"],
            sku=agent_result.get("sku"),
            sources_json=json.dumps(sources_with_context, ensure_ascii=False, default=str),
        )
        db.add(assistant_message)
        _touch_conversation(conversation, agent_result.get("sku"))
        conversation_id_value = conversation.id
        message_id_value = assistant_message.id
        db.commit()
        customer_perf_service.log_stage("save_messages_and_commit", stage_start, branch="guardrail")
        customer_perf_service.log_stage("ask_customer_service.total", request_start, branch="guardrail", intent=agent_result.get("intent"))
        customer_perf_service.summarize_request(final_answer=agent_result.get("answer"), intent=agent_result.get("intent"), agent_mode=(agent_result.get("debug") or {}).get("agent_mode"))
        release_session_connection(db)
        return {
            "conversation_id": conversation_id_value,
            "message_id": message_id_value,
            "intent": agent_result.get("intent"),
            "answer_type": agent_result.get("answer_type"),
            "confidence": agent_result.get("confidence"),
            "uncertainty": agent_result.get("uncertainty"),
            "needs_clarification": agent_result.get("needs_clarification", False),
            "anomalies": agent_result.get("anomalies") or [],
            "suggested_followups": agent_result.get("suggested_followups") or [],
            "followups": agent_result.get("followups") or agent_result.get("suggested_followups") or [],
            "warnings": agent_result.get("warnings") or [],
            "evidence": agent_result.get("evidence") or [],
            "agent_quality": agent_result.get("agent_quality") or {},
            "debug": agent_result.get("debug") or {},
            "sku": agent_result.get("sku"),
            "answer": agent_result["answer"],
            "sources": sources_with_context,
            "actions": agent_result.get("actions") or [],
            "results": agent_result.get("results") or [],
            "steps": agent_result.get("steps") or [],
        }

    context_start = perf_counter()
    entity_stack = _latest_entity_stack(db, conversation_id, user_id)
    conversation_history = _build_conversation_history(db, conversation_id, user_id)
    recommendation_context = None
    customer_perf_service.log_stage(
        "context_read",
        context_start,
        entity_stack_count=len(entity_stack or []),
        conversation_history_count=len(conversation_history or []),
        previous_result_skus_count=0,
        recommendation_context_present=bool(recommendation_context),
    )
    contextual_conversation_history = conversation_history

    shortcut_start = perf_counter()
    agent_result = await _try_named_product_shortcut(db, user_id=user_id, question=question)
    customer_perf_service.log_stage("named_product_shortcut", shortcut_start, hit=bool(agent_result), agent_mode=(agent_result.get("debug") or {}).get("agent_mode") if agent_result else None)
    if not agent_result:
        stage_start = perf_counter()
        recognized_intent = _recognized_intent_for_agent_fast_path(db, question, conversation_id)
        feedback_lessons = _build_feedback_lessons(db, user_id)
        release_session_connection(db)
        agent_result = await customer_agent_runtime_service.process_agent_request(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
            sku=None,
            previous_result_skus=[],
            entity_stack=entity_stack,
            conversation_history=contextual_conversation_history,
            feedback_lessons=feedback_lessons,
            recognized_intent=recognized_intent,
            answer_delta_callback=answer_delta_callback,
        )
        customer_perf_service.log_stage("process_agent_request", stage_start, hit=bool(agent_result), intent=agent_result.get("intent") if agent_result else None, agent_mode=(agent_result.get("debug") or {}).get("agent_mode") if agent_result else None)
    if _should_retry_with_deterministic_agent(agent_result):
        stage_start = perf_counter()
        retry_result = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=None,
            previous_result_skus=[],
        )
        customer_perf_service.log_stage("process_intent_request_retry", stage_start, hit=bool(retry_result), intent=retry_result.get("intent") if retry_result else None)
        if retry_result and retry_result.get("results"):
            agent_result = _prepare_deterministic_retry_result(retry_result)
    if not agent_result:
        stage_start = perf_counter()
        agent_result = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=None,
            previous_result_skus=[],
        )
        customer_perf_service.log_stage("process_intent_request_fallback", stage_start, hit=bool(agent_result), intent=agent_result.get("intent") if agent_result else None)
    if not agent_result:
        stage_start = perf_counter()
        agent_result = customer_agent_service.try_numeric_english_name_query(db, question)
        customer_perf_service.log_stage("legacy_rule_agent_fallback", stage_start, hit=bool(agent_result), intent=agent_result.get("intent") if agent_result else None)
    if not agent_result:
        stage_start = perf_counter()
        agent_result = customer_agent_service.process_agent_request(
            db,
            user_id=user_id,
            question=question,
            sku=None,
        )
        customer_perf_service.log_stage("legacy_rule_agent_total", stage_start, hit=bool(agent_result), intent=agent_result.get("intent") if agent_result else None)
    if agent_result:
        stage_start = perf_counter()
        agent_result = _normalize_agent_result(agent_result)
        if not agent_result.get("skip_polish"):
            agent_result["answer"] = await _polish_customer_answer(db, question, agent_result)
        agent_result = _attach_agent_quality(agent_result, question)
        conversation = _get_or_create_conversation(db, user_id, question, agent_result.get("sku"), conversation_id)
        db.add(CustomerServiceMessage(
            conversation_id=conversation.id,
            role="user",
            content=question,
            sku=agent_result.get("sku"),
        ))
        assistant_turn_index = _assistant_turn_index(db, conversation.id)
        inherited_recommendation_context = _latest_recommendation_context_for_sources(
            db,
            conversation.id,
        )
        sources_with_context = _sources_with_result_context(
            agent_result,
            turn_index=assistant_turn_index,
            user_question=question,
            inherited_recommendation_context=inherited_recommendation_context,
        )
        assistant_message = CustomerServiceMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=agent_result["answer"],
            sku=agent_result.get("sku"),
            sources_json=json.dumps(sources_with_context, ensure_ascii=False, default=str),
        )
        db.add(assistant_message)
        _touch_conversation(conversation, agent_result.get("sku"))
        conversation_id_value = conversation.id
        message_id_value = assistant_message.id
        db.commit()
        customer_perf_service.log_stage("save_messages_and_commit", stage_start, branch="agent", skip_polish=bool(agent_result.get("skip_polish")))
        customer_perf_service.log_stage("ask_customer_service.total", request_start, branch="agent", intent=agent_result.get("intent"), agent_mode=(agent_result.get("debug") or {}).get("agent_mode"))
        customer_perf_service.summarize_request(final_answer=agent_result.get("answer"), intent=agent_result.get("intent"), agent_mode=(agent_result.get("debug") or {}).get("agent_mode"))
        release_session_connection(db)
        return {
            "conversation_id": conversation_id_value,
            "message_id": message_id_value,
            "intent": agent_result.get("intent"),
            "answer_type": agent_result.get("answer_type"),
            "confidence": agent_result.get("confidence"),
            "uncertainty": agent_result.get("uncertainty"),
            "needs_clarification": agent_result.get("needs_clarification", False),
            "anomalies": agent_result.get("anomalies") or [],
            "suggested_followups": agent_result.get("suggested_followups") or [],
            "followups": agent_result.get("followups") or agent_result.get("suggested_followups") or [],
            "warnings": agent_result.get("warnings") or [],
            "evidence": agent_result.get("evidence") or [],
            "agent_quality": agent_result.get("agent_quality") or {},
            "debug": agent_result.get("debug") or {},
            "sku": agent_result.get("sku"),
            "answer": agent_result["answer"],
            "sources": sources_with_context,
            "actions": agent_result.get("actions") or [],
            "results": agent_result.get("results") or [],
            "steps": agent_result.get("steps") or [],
        }

    resolved_sku = _resolve_sku(db, question, sku)
    if not resolved_sku:
        customer_perf_service.log_stage("ask_customer_service.total", request_start, branch="guidance")
        customer_perf_service.summarize_request(final_answer="guidance", intent="clarify", agent_mode="guidance")
        return _save_and_return_guidance(db, user_id, question, conversation_id)

    knowledge_start = perf_counter()
    product = db.query(Product).filter(Product.sku == resolved_sku).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产品不存在")

    context, sources = build_product_context(db, resolved_sku, question)
    release_session_connection(db)
    messages = [
        {
            "role": "system",
            "content": (
                "你是内部产品客服助手。只能依据提供的产品上下文回答。"
                "如果上下文没有答案，必须明确说需要人工确认。"
                "不要编造参数、认证、价格、库存或售后政策。"
                "回答请先给结论，再给依据，保持中文、简洁、客服口吻。"
            ),
        },
        {
            "role": "user",
            "content": f"产品上下文：\n{context}\n\n客服问题：{question}",
        },
    ]

    try:
        answer = await customer_llm_service.chat_completion(db, messages, purpose="knowledge_answer")
    except Exception as exc:
        answer = f"聊天模型暂时不可用：{exc}"
    customer_perf_service.log_stage("single_sku_knowledge_llm", knowledge_start, sku=resolved_sku)

    conversation = _get_or_create_conversation(db, user_id, question, resolved_sku, conversation_id)
    db.add(CustomerServiceMessage(
        conversation_id=conversation.id,
        role="user",
        content=question,
        sku=resolved_sku,
    ))
    sources_with_meta = list(sources)
    sources_with_meta.append({
        "type": "agent_meta",
        "label": "客服回复元数据",
        "intent": "knowledge_base_answer",
        "answer_type": "knowledge_answer",
        "confidence": "medium",
        "uncertainty": _uncertainty_from_answer(answer, [], [], False),
        "needs_clarification": False,
        "anomalies": [],
        "suggested_followups": [],
        "followups": [],
        "warnings": [],
        "evidence": [],
        "debug": {"intent": "knowledge_base_answer", "steps": [], "warnings": [], "anomalies": [], "raw_results": []},
        "feedback": None,
    })
    assistant_message = CustomerServiceMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        sku=resolved_sku,
        sources_json=json.dumps(sources_with_meta, ensure_ascii=False, default=str),
    )
    db.add(assistant_message)
    _touch_conversation(conversation, resolved_sku)
    conversation_id_value = conversation.id
    message_id_value = assistant_message.id
    db.commit()
    customer_perf_service.log_stage("save_messages_and_commit", knowledge_start, branch="knowledge")
    customer_perf_service.log_stage("ask_customer_service.total", request_start, branch="knowledge", sku=resolved_sku)
    customer_perf_service.summarize_request(final_answer=answer, intent="knowledge_base_answer", agent_mode="single_sku_knowledge")
    release_session_connection(db)

    return {
        "conversation_id": conversation_id_value,
        "message_id": message_id_value,
        "intent": "knowledge_base_answer",
        "answer_type": "knowledge_answer",
        "confidence": "medium",
        "uncertainty": _uncertainty_from_answer(answer, [], [], False),
        "needs_clarification": False,
        "anomalies": [],
        "suggested_followups": [],
        "followups": [],
        "warnings": [],
        "evidence": [],
        "debug": {"intent": "knowledge_base_answer", "steps": [], "warnings": [], "anomalies": [], "raw_results": []},
        "sku": resolved_sku,
        "answer": answer,
        "sources": sources,
        "actions": [],
        "results": [],
        "steps": [],
    }


def build_product_context(db: Session, sku: str, question: str) -> tuple[str, list[dict]]:
    detail = product_service.get_product_detail(db, sku)
    sources: list[dict] = []
    lines = [
        f"SKU: {detail.get('sku')}",
        f"中文名: {detail.get('product_name_cn') or ''}",
        f"英文名: {detail.get('product_name_en') or ''}",
        f"品牌: {detail.get('brand') or ''}",
        f"系列: {detail.get('series') or ''}",
        f"类目: {detail.get('category') or ''} / {detail.get('sub_category') or ''}",
        f"等级: {detail.get('product_level') or ''}",
        f"生命周期: {detail.get('lifecycle_status') or ''}",
        f"负责人: {detail.get('person_in_charge') or ''}",
        f"品质情况: {detail.get('quality_note') or ''}",
    ]
    sources.append({"type": "product", "label": "产品基础信息", "sku": sku})

    specs = detail.get("specs") or {}
    if specs:
        lines.append("规格信息:")
        for key, label in [
            ("capacity", "容量"),
            ("gross_weight_g", "毛重g"),
            ("body_material", "材质"),
            ("color", "颜色"),
            ("surface_finish", "表面工艺"),
            ("heat_source", "适用热源"),
            ("power", "功率"),
            ("technical_advantages", "技术优势"),
            ("usage_instruction", "使用说明"),
        ]:
            value = specs.get(key)
            if value not in (None, "", []):
                lines.append(f"- {label}: {_stringify(value)}")
        sources.append({"type": "product_specs", "label": "产品规格", "sku": sku})

    business = detail.get("business") or {}
    if business:
        lines.append("业务信息:")
        for key, label in [
            ("top_selling_points", "核心卖点"),
            ("target_audience", "目标人群"),
            ("positioning", "定位"),
            ("price_positioning", "价格定位"),
            ("emotional_value", "情绪价值"),
            ("usage_scenarios", "使用场景"),
            ("competitor_benchmark", "竞品信息"),
        ]:
            value = business.get(key)
            if value not in (None, "", []):
                lines.append(f"- {label}: {_stringify(value)}")
        sources.append({"type": "product_business", "label": "产品业务信息", "sku": sku})

    qa_items = db.query(ProductQa).filter(ProductQa.product_id == detail["id"]).order_by(ProductQa.priority.asc().nullslast()).all()
    if qa_items:
        lines.append("产品 QA:")
        for item in qa_items[:20]:
            lines.append(f"- Q: {item.question}\n  A: {item.answer}")
        sources.append({"type": "product_qa", "label": "产品 QA", "sku": sku, "count": len(qa_items)})

    negative = db.query(ProductQaNegative).filter(ProductQaNegative.product_id == detail["id"]).first()
    if negative:
        lines.append("差评/负面问题应答:")
        if negative.high_freq_negative_words:
            lines.append(f"- 高频负面词: {negative.high_freq_negative_words}")
        if negative.response_tone:
            lines.append(f"- 应答口径: {negative.response_tone}")
        sources.append({"type": "product_qa_negative", "label": "差评应答", "sku": sku})

    knowledge = knowledge_service.keyword_retrieve(db, question, sku=sku, limit=5)
    if knowledge:
        lines.append("知识库补充:")
        for item in knowledge:
            lines.append(f"- {item['content']}")
        sources.append({"type": "knowledge_base", "label": "向量/知识库补充", "sku": sku, "count": len(knowledge)})

    return "\n".join(lines), sources


def review_samples(db: Session, user_id: str, limit: int = 100) -> dict:
    user_id = str(user_id)
    messages = (
        db.query(CustomerServiceMessage, CustomerServiceConversation)
        .join(CustomerServiceConversation, CustomerServiceConversation.id == CustomerServiceMessage.conversation_id)
        .filter(
            CustomerServiceConversation.user_id == user_id,
            CustomerServiceMessage.role == "assistant",
        )
        .order_by(CustomerServiceMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    items = []
    frequent_questions: dict[str, int] = {}
    clarification_samples = 0
    anomaly_samples = 0
    for assistant_message, conversation in messages:
        meta = _message_meta(assistant_message.sources_json)
        user_message = (
            db.query(CustomerServiceMessage)
            .filter(
                CustomerServiceMessage.conversation_id == conversation.id,
                CustomerServiceMessage.role == "user",
                CustomerServiceMessage.created_at <= assistant_message.created_at,
            )
            .order_by(CustomerServiceMessage.created_at.desc())
            .first()
        )
        question = (user_message.content if user_message else "").strip()
        if question:
            frequent_questions[question] = frequent_questions.get(question, 0) + 1
        if meta.get("needs_clarification"):
            clarification_samples += 1
        if meta.get("anomalies"):
            anomaly_samples += 1
        items.append({
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
            "question": question,
            "answer": assistant_message.content,
            "intent": meta.get("intent"),
            "confidence": meta.get("confidence"),
            "agent_quality": meta.get("agent_quality", {}),
            "needs_clarification": meta.get("needs_clarification", False),
            "anomalies": meta.get("anomalies", []),
            "warnings": meta.get("warnings", []),
            "suggested_followups": meta.get("suggested_followups", []),
            "created_at": str(assistant_message.created_at),
        })

    top_questions = sorted(frequent_questions.items(), key=lambda item: item[1], reverse=True)[:20]
    quality_summary = _review_quality_summary(items)
    return {
        "items": items,
        "summary": {
            "total_samples": len(items),
            "clarification_samples": clarification_samples,
            "anomaly_samples": anomaly_samples,
            "quality": quality_summary,
            "top_questions": [{"question": question, "count": count} for question, count in top_questions],
        },
    }


def _resolve_sku(db: Session, question: str, sku: str | None) -> str | None:
    if sku:
        return sku.strip()
    candidates = SKU_RE.findall(question)
    for candidate in candidates:
        product = db.query(Product).filter(Product.sku.ilike(candidate)).first()
        if product:
            return product.sku
    return None


def _get_or_create_conversation(
    db: Session,
    user_id: str,
    question: str,
    sku: str | None,
    conversation_id: str | None,
) -> CustomerServiceConversation:
    user_id = str(user_id)
    if conversation_id:
        conversation = db.query(CustomerServiceConversation).filter(
            CustomerServiceConversation.id == conversation_id,
            CustomerServiceConversation.user_id == user_id,
        ).first()
        if not conversation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客服会话不存在")
        return conversation

    conversation = CustomerServiceConversation(
        user_id=user_id,
        title=_make_title(question, sku),
        sku=sku,
    )
    db.add(conversation)
    db.flush()
    return conversation


def _touch_conversation(conversation: CustomerServiceConversation, sku: str | None = None) -> None:
    if sku:
        conversation.sku = sku
    conversation.updated_at = datetime.now(timezone.utc)


def _sources_with_result_context(
    agent_result: dict,
    turn_index: int | None = None,
    user_question: str | None = None,
    inherited_recommendation_context: dict | None = None,
) -> list[dict]:
    sources = list(agent_result.get("sources") or [])
    entities = _entities_from_agent_result(agent_result)
    result_skus = [item["sku"] for item in entities]
    recommendation_context = None
    if agent_result.get("intent") == "recommend_products" and result_skus:
        product_scope = customer_dialogue_state.product_scope_from_text(str(user_question or ""))
        if not product_scope and isinstance(inherited_recommendation_context, dict):
            product_scope = str(inherited_recommendation_context.get("product_scope") or "").strip()
        recommendation_context = {
            "recommended_skus": result_skus,
            "user_question": str(user_question or "").strip(),
            "product_scope": product_scope,
        }
    elif isinstance(inherited_recommendation_context, dict) and inherited_recommendation_context.get("recommended_skus"):
        recommendation_context = {
            "recommended_skus": [
                str(sku).strip().upper()
                for sku in inherited_recommendation_context.get("recommended_skus") or []
                if str(sku or "").strip()
            ],
            "user_question": str(inherited_recommendation_context.get("user_question") or "").strip(),
            "product_scope": str(inherited_recommendation_context.get("product_scope") or "").strip(),
        }
    meta_entry = {
        "type": "agent_meta",
        "label": "客服回复元数据",
        "intent": agent_result.get("intent"),
        "answer_type": agent_result.get("answer_type"),
        "confidence": agent_result.get("confidence"),
        "uncertainty": agent_result.get("uncertainty"),
        "needs_clarification": agent_result.get("needs_clarification", False),
        "anomalies": agent_result.get("anomalies") or [],
        "suggested_followups": agent_result.get("suggested_followups") or agent_result.get("followups") or [],
        "followups": agent_result.get("followups") or agent_result.get("suggested_followups") or [],
        "warnings": agent_result.get("warnings") or [],
        "evidence": agent_result.get("evidence") or [],
        "agent_quality": agent_result.get("agent_quality") or {},
        "debug": agent_result.get("debug") or {},
        "feedback": agent_result.get("feedback") or None,
    }
    if recommendation_context:
        meta_entry["recommendation_context"] = recommendation_context
    sources.append(meta_entry)
    if agent_result.get("steps"):
        sources.append({"type": "agent_steps", "label": "Agent执行过程", "steps": agent_result.get("steps")})
    if result_skus:
        context_entry = {
            "type": "agent_context",
            "label": "上下文结果",
            "result_skus": result_skus,
            "current_sku": agent_result.get("sku") if agent_result.get("sku") in result_skus else (result_skus[0] if len(result_skus) == 1 else None),
            "entities": entities,
            "count": len(result_skus),
        }
        if turn_index is not None:
            context_entry["turn_index"] = turn_index
        sources.append(context_entry)
    return sources


def _latest_recommendation_context_for_sources(db: Session, conversation_id: str | None) -> dict:
    if not conversation_id:
        return {}
    messages = (
        db.query(CustomerServiceMessage)
        .filter(
            CustomerServiceMessage.conversation_id == conversation_id,
            CustomerServiceMessage.role == "assistant",
        )
        .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
        .limit(5)
        .all()
    )
    for message in messages:
        for source in _safe_json(message.sources_json, []):
            if not isinstance(source, dict) or source.get("type") != "agent_meta":
                continue
            context = source.get("recommendation_context")
            if isinstance(context, dict) and context.get("recommended_skus"):
                return context
    return {}


def _recognized_intent_for_agent_fast_path(db: Session, question: str, conversation_id: str | None) -> str | None:
    intent = customer_agent_intent_service.parse_intent(question, previous_result_skus=[])
    if intent and getattr(intent, "intent", "") == "recommend_products":
        return "recommend_products"
    if _asks_for_alternative_recommendation(question) and _latest_recommendation_context_for_sources(db, conversation_id):
        return "recommend_products"
    return getattr(intent, "intent", None) if intent else None


def _asks_for_alternative_recommendation(question: str) -> bool:
    text = str(question or "")
    terms = (
        "\u6362\u4e00\u4e2a",
        "\u6362\u4e00\u6b3e",
        "\u6362\u4e2a",
        "\u518d\u63a8\u8350",
        "\u53e6\u5916\u63a8\u8350",
        "\u4e0d\u8981\u521a\u624d",
        "\u522b\u8981\u521a\u624d",
    )
    return any(term in text for term in terms)


def _entities_from_agent_result(agent_result: dict, limit: int = 20) -> list[dict]:
    entities: list[dict] = []
    seen: set[str] = set()

    def add_entity(raw: dict, role: str, source: str) -> None:
        sku = str(raw.get("sku") or "").strip().upper()
        if not sku or "," in sku or sku in seen or len(entities) >= limit:
            return
        seen.add(sku)
        entities.append({
            "sku": sku,
            "name": raw.get("product_name_cn") or raw.get("product_name_en") or raw.get("name") or "",
            "turn": None,
            "role": role,
            "source": source,
        })

    primary_sku = str(agent_result.get("sku") or "").strip().upper()
    for item in agent_result.get("results") or []:
        if isinstance(item, dict):
            role = "current" if primary_sku and str(item.get("sku") or "").strip().upper() == primary_sku else "result"
            add_entity(item, role, "results")
    for action in agent_result.get("actions") or []:
        if isinstance(action, dict):
            add_entity(action, "current" if len(entities) == 0 else "result", "actions")
    if primary_sku and primary_sku not in seen:
        add_entity({"sku": primary_sku}, "current", "sku")
    return entities


def _steps_from_sources(sources_json: str | None) -> list[dict]:
    for source in _safe_json(sources_json, []):
        if isinstance(source, dict) and source.get("type") == "agent_steps":
            return source.get("steps") or []
    return []


def _message_meta(sources_json: str | None) -> dict:
    for source in _safe_json(sources_json, []):
        if isinstance(source, dict) and source.get("type") == "agent_meta":
            return source
    return {}


def _normalize_agent_result(agent_result: dict) -> dict:
    result = dict(agent_result)
    results = result.get("results") or []
    warnings = result.get("warnings") or []
    result.setdefault("answer_type", _answer_type_from_intent(result.get("intent")))
    result.setdefault("uncertainty", _uncertainty_from_answer(result.get("answer") or "", results, warnings, result.get("needs_clarification", False)))
    result.setdefault("evidence", _evidence_from_results(results))
    result.setdefault("followups", result.get("suggested_followups") or [])
    result.setdefault("suggested_followups", result.get("followups") or [])
    result.setdefault("agent_quality", {})
    result.setdefault("debug", {
        "intent": result.get("intent"),
        "steps": result.get("steps") or [],
        "warnings": warnings,
        "anomalies": result.get("anomalies") or [],
        "raw_results": results,
    })
    return result


def _should_retry_with_deterministic_agent(agent_result: dict | None) -> bool:
    if not agent_result:
        return False
    if agent_result.get("results") or _has_usable_agent_answer(agent_result):
        return False
    warnings = set(agent_result.get("warnings") or [])
    if "missing_product_results" in warnings:
        return True
    if agent_result.get("needs_clarification") and not agent_result.get("results"):
        return True
    return str(agent_result.get("confidence") or "").lower() == "low" and not agent_result.get("results")


def _has_usable_agent_answer(agent_result: dict) -> bool:
    answer = str(agent_result.get("answer") or "").strip()
    if not answer:
        return False
    unusable_markers = (
        "没有找到足够匹配",
        "没有找到匹配",
        "未找到匹配",
        "未找到足够",
        "no matching",
        "not enough matching",
    )
    normalized_answer = answer.lower()
    return not any(marker in normalized_answer for marker in unusable_markers)


def _prepare_deterministic_retry_result(retry_result: dict) -> dict:
    result = dict(retry_result)
    if result.get("results"):
        result["skip_polish"] = True
    return result


_FAQ_PURCHASE_TERMS = (
    "哪里买",
    "在哪里买",
    "可以买到",
    "怎么买",
    "购买链接",
    "购买渠道",
    "官网吗",
    "旗舰店",
    "淘宝",
    "天猫",
    "京东",
    "拼多多",
    "抖音",
)
_FAQ_AFTERSALES_TERMS = (
    "售后",
    "退换",
    "退货",
    "换货",
    "保修",
    "质保",
    "客服",
    "坏了怎么办",
    "有瑕疵怎么办",
)
_FAQ_AFTERSALES_PROBLEM_TERMS = ("问题", "质量", "坏了", "瑕疵", "破损")
_FAQ_AFTERSALES_HELP_TERMS = ("怎么办", "怎么处理", "找谁", "谁处理", "联系谁")
_FAQ_COMPANY_TERMS = (
    "公司在哪里",
    "公司地址",
    "地址",
    "联系方式",
    "电话",
    "营业时间",
    "工作时间",
    "上班时间",
)
_FAQ_GREETING_TERMS = ("你好", "您好", "谢谢", "再见", "拜拜", "hello", "hi")


def _is_customer_faq_question(question: str) -> bool:
    return _classify_customer_faq_intent(question) is not None


def _classify_customer_faq_intent(question: str) -> str | None:
    text = str(question or "").strip()
    if not text:
        return None
    normalized = customer_cache_service.normalize_text(text)
    if any(term in normalized for term in _FAQ_GREETING_TERMS):
        return "greeting"
    if any(term in text for term in _FAQ_PURCHASE_TERMS):
        return "purchase_channel"
    if any(term in text for term in _FAQ_AFTERSALES_TERMS):
        return "aftersales"
    if _is_unscoped_aftersales_help_request(text):
        return "aftersales"
    if any(term in text for term in _FAQ_COMPANY_TERMS):
        return "company_info"
    return None


def _is_unscoped_aftersales_help_request(text: str) -> bool:
    if not text or SKU_RE.search(text):
        return False
    has_problem_signal = any(term in text for term in _FAQ_AFTERSALES_PROBLEM_TERMS)
    has_help_signal = any(term in text for term in _FAQ_AFTERSALES_HELP_TERMS)
    return has_problem_signal and has_help_signal


async def _answer_customer_faq_fast_path(db: Session, question: str, intent: str) -> dict | None:
    cache_key = customer_cache_service.make_key("faq_fast_path", id(db), intent, customer_cache_service.normalize_text(question))
    cached = customer_cache_service.faq_cache.get(cache_key)
    if cached is not None:
        return cached

    if intent == "greeting":
        result = _build_customer_faq_result(
            question=question,
            intent=intent,
            answer="你好，我可以帮你查询产品资料、购买渠道、售后和公司信息。",
            sources=[{"type": "faq", "label": "问候快捷回复"}],
            confidence="high",
        )
        customer_cache_service.faq_cache.set(cache_key, result)
        return result

    structured = _lookup_structured_faq_answer(db, question, intent)
    if structured:
        customer_cache_service.faq_cache.set(cache_key, structured)
        return structured

    knowledge_result = await _lookup_faq_from_knowledge(db, question, intent)
    if knowledge_result:
        customer_cache_service.faq_cache.set(cache_key, knowledge_result)
        return knowledge_result

    result = _build_customer_faq_result(
        question=question,
        intent=intent,
        answer="目前系统里暂未配置具体购买渠道/售后联系方式，建议联系人工客服确认。我可以继续帮你查询产品材质、规格、适用场景等资料。",
        sources=[{"type": "faq", "label": "未配置 FAQ 资料"}],
        confidence="low",
        uncertainty="faq_not_configured",
        warnings=["faq_data_missing"],
    )
    customer_cache_service.faq_cache.set(cache_key, result)
    return result


def _lookup_structured_faq_answer(db: Session, question: str, intent: str) -> dict | None:
    if intent == "purchase_channel":
        channels = product_service.get_listing_channels(db)
        items = []
        for channel in channels[:8]:
            name = getattr(channel, "channel_name", None)
            if not name:
                continue
            items.append(f"{name}{('（' + channel.channel_code + '）') if getattr(channel, 'channel_code', None) else ''}")
        if not items:
            return None
        answer = "系统里记录的销售渠道包括：" + "、".join(items[:8]) + "。"
        return _build_customer_faq_result(
            question=question,
            intent=intent,
            answer=answer,
            sources=[{"type": "structured_faq", "label": "销售渠道", "count": len(items)}],
            confidence="high",
            answer_type="faq",
            agent_mode="purchase_channel_fast_path",
            result_skus=[],
        )
    if intent == "aftersales":
        return _build_customer_faq_result(
            question=question,
            intent=intent,
            answer="目前系统里暂未配置可直接公开的售后电话。建议通过购买渠道的店铺客服或官方客服入口联系人工售后确认，我也可以继续帮你查询产品材质、规格和使用说明。",
            sources=[{"type": "structured_faq", "label": "售后联系方式未配置", "count": 0}],
            confidence="high",
            answer_type="faq",
            agent_mode="customer_faq_fast_path",
            result_skus=[],
        )
    return None


async def _lookup_faq_from_knowledge(db: Session, question: str, intent: str) -> dict | None:
    category_map = {
        "purchase_channel": ("purchase_channel", "faq", "company_info"),
        "aftersales": ("aftersales", "faq"),
        "company_info": ("company_info", "faq"),
    }
    categories = category_map.get(intent)
    if not categories:
        return None
    cache_key = customer_cache_service.make_key("faq_knowledge", id(db), intent, customer_cache_service.normalize_text(question))
    cached = customer_cache_service.faq_cache.get(cache_key)
    if cached is not None:
        return cached
    limit = 3
    try:
        rows = await knowledge_service.semantic_retrieve(db, question, limit=limit)
    except Exception:
        rows = knowledge_service.keyword_retrieve(db, question, limit=limit)
    filtered_rows = []
    for row in rows[:limit]:
        metadata = row.get("metadata") if isinstance(row, dict) else {}
        source_type = str(row.get("source_type") or "").strip().lower() if isinstance(row, dict) else ""
        category = str(metadata.get("category") or metadata.get("type") or source_type).strip().lower()
        content = str(row.get("content") or "").strip() if isinstance(row, dict) else ""
        if category in categories or any(term in content for term in categories):
            filtered_rows.append(row)
    if not filtered_rows:
        return None
    snippets = []
    for row in filtered_rows[:3]:
        content = str(row.get("content") or "").strip()
        if content:
            snippets.append(content[:220])
    if not snippets:
        return None
    if intent == "purchase_channel":
        answer = "根据系统里已有资料，可参考：" + "；".join(snippets)
    elif intent == "aftersales":
        answer = "系统里记录的售后资料如下：" + "；".join(snippets)
    else:
        answer = "系统里记录的公司信息如下：" + "；".join(snippets)
    result = _build_customer_faq_result(
        question=question,
        intent=intent,
        answer=answer[:3000],
        sources=[{"type": "faq_knowledge", "label": intent, "count": len(filtered_rows), "results": filtered_rows[:3]}],
        confidence="medium",
        answer_type="faq",
        agent_mode="customer_faq_fast_path",
        result_skus=[],
    )
    customer_cache_service.faq_cache.set(cache_key, result)
    return result


def _build_customer_faq_result(
    *,
    question: str,
    intent: str,
    answer: str,
    sources: list[dict],
    confidence: str = "high",
    answer_type: str = "faq",
    agent_mode: str = "customer_faq_fast_path",
    uncertainty: str = "resolved",
    warnings: list[str] | None = None,
    result_skus: list[str] | None = None,
) -> dict:
    result_skus = result_skus or []
    warnings = warnings or []
    result = {
        "answer": answer,
        "intent": intent,
        "answer_type": answer_type,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "needs_clarification": False,
        "anomalies": [],
        "suggested_followups": [],
        "followups": [],
        "evidence": [],
        "sources": sources,
        "actions": [],
        "results": [],
        "steps": [{"type": "faq_fast_path", "label": "FAQ 快速路径", "detail": intent, "ok": True}],
        "warnings": warnings,
        "sku": None,
        "result_skus": result_skus,
        "debug": {
            "agent_mode": agent_mode,
            "intent": intent,
            "question": question,
            "steps": [{"type": "faq_fast_path", "label": "FAQ 快速路径", "detail": intent, "ok": True}],
            "warnings": warnings,
            "anomalies": [],
            "raw_results": [],
            "tool_results": [],
        },
        "skip_polish": True,
    }
    quality = customer_agent_quality_service.evaluate_agent_response(
        question,
        answer=result["answer"],
        intent=result["intent"],
        results=result["results"],
        sources=result["sources"],
        actions=result["actions"],
        warnings=result["warnings"],
        needs_clarification=result["needs_clarification"],
        direct_answer=True,
        tool_results=[],
    )
    result["agent_quality"] = quality
    result["debug"]["agent_quality"] = quality
    return result


async def _try_named_product_shortcut(db: Session, *, user_id: str, question: str) -> dict | None:
    products = _products_named_in_question(db, question)
    if not products:
        return None
    if _is_variant_compare_question(question) and len(products) >= 2:
        sku_text = " 和 ".join(product.sku for product in products[:3])
        return await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=f"{sku_text} 有什么区别？客户该选哪个？",
            sku=None,
            previous_result_skus=[],
        )
    if len(products) == 1 and _is_generic_named_product_question(question):
        detail = product_service.get_product_detail(db, products[0].sku)
        return _named_product_context_result(question, detail)
    return None


def _is_generic_named_product_question(question: str) -> bool:
    text = str(question or "")
    specific_terms = (
        "材质", "材料", "功率", "认证", "食品级", "水洗", "冷水", "冲洗", "清洗", "热源", "燃料",
        "表面处理", "表面工艺", "爆炒", "大火", "颜色", "容量", "重量", "尺寸", "安全", "不粘", "不沾",
    )
    if any(term in text for term in specific_terms):
        return False
    return any(term in text for term in ("怎么样", "介绍一下", "适合露营吗", "适合户外吗", "适合吗", "好用吗"))


def _products_named_in_question(db: Session, question: str) -> list[Product]:
    text = customer_agent_service.normalize_search_text(question)
    lower = text.lower()
    products = db.query(Product).all()
    matched: list[Product] = []
    for product in products:
        names = [product.sku, product.product_name_cn, product.product_name_en]
        for raw_name in names:
            name = str(raw_name or "").strip()
            if len(name) < 2:
                continue
            name_lower = name.lower()
            base_name = re.sub(r"\s*pro$", "", name_lower, flags=re.I)
            if name_lower in lower or (name_lower.endswith("pro") and "pro" in lower and base_name in lower):
                matched.append(product)
                break
    matched.sort(key=lambda item: (("pro" not in (item.product_name_cn or "").lower()), -(len(item.product_name_cn or ""))))
    return matched


def _is_variant_compare_question(question: str) -> bool:
    text = str(question or "")
    return "pro" in text.lower() and any(word in text for word in ("选", "对比", "比较", "区别", "哪个", "怎么回复"))


def _named_product_context_result(question: str, detail: dict) -> dict:
    specs = detail.get("specs") or {}
    business = detail.get("business") or {}
    name = detail.get("product_name_cn") or detail.get("product_name_en") or detail.get("sku")
    sku = detail.get("sku")
    scenarios = _display_value(business.get("usage_scenarios"))
    features = _display_value(business.get("top_selling_points"))
    capacity = _display_value(specs.get("capacity"))
    material = _display_value(specs.get("body_material"))
    answer_parts = [
        f"{name}（{sku}）可以结合这个场景判断。",
        f"类目：{detail.get('category') or '未标注'}。",
    ]
    if scenarios:
        answer_parts.append(f"适用场景：{scenarios}。")
    if features:
        answer_parts.append(f"主要卖点：{features}。")
    if capacity:
        answer_parts.append(f"容量/规格：{capacity}。")
    if material:
        answer_parts.append(f"材质：{material}。")
    if "水壶" in question or "餐具" in question or "带" in question:
        answer_parts.append("如果要携带餐具、水壶等物品，建议按实际尺寸和数量确认；小件随身/收纳适合，大件或整套锅具不建议强行装。")
    return {
        "answer": "".join(answer_parts),
        "intent": "product_detail",
        "answer_type": "product_detail",
        "confidence": "high",
        "uncertainty": "confirmed",
        "needs_clarification": False,
        "sources": [{"type": "product", "label": "命名产品资料", "sku": sku}],
        "actions": [],
        "results": [{
            "sku": sku,
            "product_name_cn": detail.get("product_name_cn"),
            "category": detail.get("category"),
            "capacity": capacity,
            "body_material": material,
            "features": features,
            "usage_scenarios": scenarios,
        }],
        "steps": [{"type": "named_product_shortcut", "label": "命名产品优先", "detail": f"命中 {sku}", "ok": True}],
        "warnings": [],
        "evidence": [],
        "debug": {"agent_mode": "named_product_shortcut"},
        "sku": sku,
        "skip_polish": True,
    }


def _display_value(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        return "，".join(_display_value(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        label = _display_value(value.get("label"))
        item_value = _display_value(value.get("value"))
        if label and item_value:
            return item_value if label == item_value else f"{label} {item_value}"
        for key in ("value", "label", "text", "name"):
            if value.get(key) not in (None, ""):
                return _display_value(value.get(key))
        return "，".join(f"{key}: {_display_value(item)}" for key, item in value.items() if item not in (None, ""))
    return str(value).strip()


def _attach_agent_quality(agent_result: dict, question: str) -> dict:
    result = dict(agent_result)
    if result.get("agent_quality"):
        return result
    quality = customer_agent_quality_service.evaluate_agent_response(
        question,
        answer=result.get("answer") or "",
        intent=result.get("intent") or "",
        results=result.get("results") or [],
        sources=result.get("sources") or [],
        actions=result.get("actions") or [],
        warnings=result.get("warnings") or [],
        needs_clarification=bool(result.get("needs_clarification")),
        direct_answer=not bool(result.get("sources") or result.get("actions") or result.get("results")),
        tool_results=(result.get("debug") or {}).get("tool_results") or [],
    )
    result["agent_quality"] = quality
    debug = dict(result.get("debug") or {})
    debug["agent_quality"] = quality
    result["debug"] = debug
    if quality.get("level") == "low":
        result["confidence"] = "low"
    elif not quality.get("passed") and result.get("confidence") == "high":
        result["confidence"] = "medium"
    if quality.get("risks"):
        result["warnings"] = list(dict.fromkeys([*(result.get("warnings") or []), *quality["risks"]]))
        result["debug"]["warnings"] = result["warnings"]
    return result


def _review_quality_summary(items: list[dict]) -> dict:
    scores = []
    levels: dict[str, int] = {}
    risks: dict[str, int] = {}
    for item in items:
        quality = item.get("agent_quality") or {}
        if quality.get("score") is not None:
            scores.append(float(quality.get("score") or 0))
        level = str(quality.get("level") or "unknown")
        levels[level] = levels.get(level, 0) + 1
        for risk in quality.get("risks") or []:
            key = str(risk).split(":", 1)[0]
            risks[key] = risks.get(key, 0) + 1
    top_risks = sorted(risks.items(), key=lambda item: item[1], reverse=True)[:8]
    return {
        "avg_score": round(sum(scores) / max(len(scores), 1), 3) if scores else None,
        "levels": levels,
        "top_risks": [{"risk": risk, "count": count} for risk, count in top_risks],
    }


async def _polish_customer_answer(db: Session, question: str, agent_result: dict) -> str:
    answer = str(agent_result.get("answer") or "").strip()
    if not answer or agent_result.get("answer_type") == "action_proposal":
        return answer
    evidence = agent_result.get("evidence") or []
    if not evidence and agent_result.get("uncertainty") == "confirmed":
        return answer
    payload = {
        "question": question,
        "draft_answer": answer,
        "uncertainty": agent_result.get("uncertainty"),
        "evidence": evidence[:8],
        "followups": (agent_result.get("followups") or agent_result.get("suggested_followups") or [])[:3],
    }
    system = (
        "你是产品客服话术润色器。只能依据输入的 draft_answer、evidence、uncertainty 和 followups 改写，"
        "不得新增事实、参数、认证、价格、库存或承诺。"
        "如果 uncertainty 不是 confirmed，必须保留“资料未标注/不能确认/需要人工确认”的含义。"
        "输出纯中文客服回答，不要输出 JSON，不要出现意图、置信度、Agent、调试、异常提示等工程词。"
        "不要逐字分析或引用用户问题中的措辞（如人数、场景词），用户问题只提供上下文。"
    )
    try:
        polished = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=800,
            purpose="polish",
        )
    except Exception:
        return answer
    polished = str(polished or "").strip()
    if not polished:
        return answer
    forbidden = ("意图", "置信度", "Agent", "执行过程", "异常提示")
    if any(item in polished for item in forbidden):
        return answer
    if agent_result.get("uncertainty") != "confirmed" and not any(item in polished for item in ("未标注", "不能确认", "人工确认", "资料不足", "暂不能确认")):
        return answer
    return polished


def _answer_type_from_intent(intent: str | None) -> str:
    return {
        "query_products": "product_query",
        "product_detail": "product_detail",
        "compare_products": "comparison",
        "recommend_products": "recommendation",
        "propose_delete": "action_proposal",
        "propose_update": "action_proposal",
        "clarify": "clarification",
    }.get(str(intent or ""), "unknown")


def _uncertainty_from_answer(answer: str, results: list, warnings: list, needs_clarification: bool) -> str:
    if needs_clarification:
        return "ambiguous_product"
    if any(item in answer for item in ("没有标注", "不能直接确认", "暂时不能确认", "资料未标注")):
        return "not_recorded"
    if not results and any(item in answer for item in ("没有找到", "暂时无法", "不能可靠")):
        return "insufficient_data"
    if warnings:
        return "insufficient_data"
    return "confirmed"


def _evidence_from_results(results: list) -> list[dict]:
    evidence = []
    for item in results[:8]:
        if not isinstance(item, dict):
            continue
        field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
        if field_values:
            for label, value in field_values.items():
                evidence.append({
                    "sku": item.get("sku"),
                    "product_name": item.get("product_name_cn") or item.get("product_name_en"),
                    "field_label": label,
                    "value": value,
                    "source_layer": _layer_for_field_label(str(label)),
                    "matched_by": item.get("matched_by") or "产品资料",
                })
            continue
        for label, key in (("容量", "capacity"), ("材质", "body_material"), ("颜色", "color"), ("负责人", "person_in_charge"), ("类目", "category"), ("卖点", "features")):
            value = item.get(key)
            if value not in (None, ""):
                evidence.append({
                    "sku": item.get("sku"),
                    "product_name": item.get("product_name_cn") or item.get("product_name_en"),
                    "field_label": label,
                    "value": _stringify(value),
                    "source_layer": _layer_for_field_label(label),
                    "matched_by": item.get("matched_by") or "产品资料",
                })
    return evidence


def _layer_for_field_label(label: str) -> str:
    if any(item in label for item in ("容量", "重量", "材质", "颜色", "热源", "功率", "表面")):
        return "L2"
    if any(item in label for item in ("卖点", "场景", "定位", "人群", "竞品")):
        return "L3"
    if any(item in label for item in ("标题", "描述", "关键词", "listing", "Listing")):
        return "L4"
    return "L1"



def _build_conversation_history(db: Session, conversation_id: str | None, user_id: str) -> list[dict]:
    """Build conversation context from DB history (last 10 turns)."""
    if not conversation_id:
        return []
    conversation = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.id == conversation_id,
        CustomerServiceConversation.user_id == str(user_id),
    ).first()
    if not conversation:
        return []
    messages = db.query(CustomerServiceMessage).filter(
        CustomerServiceMessage.conversation_id == conversation.id
    ).order_by(CustomerServiceMessage.created_at.desc()).limit(20).all()
    history = []
    for msg in reversed(messages):
        role = "assistant" if msg.role == "assistant" else "user"
        history.append({"role": role, "content": msg.content})
    return history


def _build_feedback_lessons(db: Session, user_id: str, limit: int = 8) -> list[dict]:
    messages = (
        db.query(CustomerServiceMessage)
        .join(CustomerServiceConversation, CustomerServiceConversation.id == CustomerServiceMessage.conversation_id)
        .filter(
            CustomerServiceConversation.user_id == str(user_id),
            CustomerServiceMessage.role == "assistant",
        )
        .order_by(CustomerServiceMessage.created_at.desc())
        .limit(50)
        .all()
    )
    lessons = []
    for message in messages:
        meta = _message_meta(message.sources_json)
        feedback = meta.get("feedback") if isinstance(meta, dict) else None
        if not isinstance(feedback, dict) or feedback.get("rating") == "helpful":
            continue
        user_message = (
            db.query(CustomerServiceMessage)
            .filter(
                CustomerServiceMessage.conversation_id == message.conversation_id,
                CustomerServiceMessage.role == "user",
                CustomerServiceMessage.created_at <= message.created_at,
            )
            .order_by(CustomerServiceMessage.created_at.desc())
            .first()
        )
        lessons.append({
            "question": user_message.content if user_message else "",
            "bad_answer": message.content[:500],
            "rating": feedback.get("rating"),
            "reason": feedback.get("reason") or "",
            "comment": feedback.get("comment") or "",
        })
        if len(lessons) >= limit:
            break
    return lessons


def _latest_result_skus(db: Session, conversation_id: str | None, user_id: str) -> list[str]:
    return [item["sku"] for item in _latest_entity_stack(db, conversation_id, user_id)[:10]]


def _latest_entity_stack(db: Session, conversation_id: str | None, user_id: str, limit: int = 30) -> list[dict]:
    if not conversation_id:
        return []
    conversation = db.query(CustomerServiceConversation).filter(
        CustomerServiceConversation.id == conversation_id,
        CustomerServiceConversation.user_id == str(user_id),
    ).first()
    if not conversation:
        return []
    messages = db.query(CustomerServiceMessage).filter(
        CustomerServiceMessage.conversation_id == conversation_id,
        CustomerServiceMessage.role == "assistant",
    ).order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc()).limit(5).all()
    records: list[tuple[int, int, int, dict]] = []
    for message_index, message in enumerate(messages):
        for source in _safe_json(message.sources_json, []):
            if not isinstance(source, dict) or source.get("type") != "agent_context":
                continue
            source_turn_index = source.get("turn_index")
            turn_index = source_turn_index if isinstance(source_turn_index, int) else message_index
            entities = source.get("entities") or []
            if entities:
                for entity_index, raw in enumerate(entities):
                    if not isinstance(raw, dict):
                        continue
                    sku = str(raw.get("sku") or "").strip().upper()
                    if not sku:
                        continue
                    entity = dict(raw)
                    entity["sku"] = sku
                    entity.setdefault("name", "")
                    entity["turn"] = turn_index
                    records.append((turn_index, message_index, entity_index, entity))
                continue
            for entity_index, sku in enumerate(source.get("result_skus") or []):
                sku = str(sku or "").strip().upper()
                if not sku:
                    continue
                records.append((turn_index, message_index, entity_index, {"sku": sku, "name": "", "turn": turn_index, "role": "result", "source": "legacy_context"}))
        if message.sku:
            sku = str(message.sku).strip().upper()
            if sku:
                records.append((message_index, message_index, 0, {"sku": sku, "name": "", "turn": message_index, "role": "current", "source": "message_sku"}))
        primary_sku = _primary_sku_from_message_content(message.content)
        if primary_sku:
            records.append((message_index, message_index, 1, {"sku": primary_sku, "name": "", "turn": message_index, "role": "current", "source": "message_content"}))
    records.sort(key=lambda item: (-item[0], -item[1], item[2]))
    stack: list[dict] = []
    seen: set[str] = set()
    for _, _, _, entity in records:
        sku = str(entity.get("sku") or "").strip().upper()
        if not sku:
            continue
        if sku in seen:
            existing = next(item for item in stack if item.get("sku") == sku)
            if not existing.get("name") and entity.get("name"):
                existing["name"] = entity["name"]
            continue
        seen.add(sku)
        stack.append(entity)
        if len(stack) >= limit:
            return stack
    return stack


def _should_use_previous_result_skus(question: str) -> bool:
    text = str(question or "")
    explicit_refs = (
        "这些", "这几个", "这几款", "刚才", "上面", "上一轮", "前面",
        "他", "他的", "它", "它的", "该产品", "它们", "他们", "哪个", "哪款", "哪种", "这款", "那款", "这个", "那个", "其中",
    )
    if any(item in text for item in explicit_refs):
        return True
    if len(text) <= 12 and any(item in text for item in ("容量", "材质", "卖点", "价格", "适合", "好不好")):
        return True
    return False


def _should_use_conversation_history(question: str) -> bool:
    text = str(question or "")
    if _should_use_previous_result_skus(text):
        return True
    followup_starts = ("那", "如果", "那如果", "还有", "另外", "继续", "改成", "换成")
    if text.startswith(followup_starts) and len(text) <= 30:
        return True
    return False


def _save_and_return_guidance(db: Session, user_id: str, question: str, conversation_id: str | None) -> dict:
    conversation = _get_or_create_conversation(db, user_id, question, None, conversation_id)
    answer = "先说结论：我还不能可靠回答这个问题，因为当前没有识别到明确的产品范围。\n下一步建议：请先输入 SKU，或者先让我查一批产品，再继续追问。"
    agent_quality = customer_agent_quality_service.evaluate_agent_response(
        question,
        answer=answer,
        intent="clarify",
        results=[],
        sources=[{"type": "agent_clarification", "label": "需要明确产品范围"}],
        actions=[],
        warnings=[],
        needs_clarification=True,
    )
    meta_sources = [{
        "type": "agent_meta",
        "label": "客服回复元数据",
        "intent": "clarify",
        "answer_type": "clarification",
        "confidence": "low",
        "uncertainty": "ambiguous_product",
        "needs_clarification": True,
        "anomalies": [],
        "suggested_followups": ["你可以直接给我 SKU，或者让我先列出某个类目的产品。"],
        "followups": ["你可以直接给我 SKU，或者让我先列出某个类目的产品。"],
        "warnings": [],
        "evidence": [],
        "agent_quality": agent_quality,
        "debug": {"intent": "clarify", "steps": [], "warnings": [], "anomalies": [], "raw_results": []},
        "feedback": None,
    }]
    db.add(CustomerServiceMessage(conversation_id=conversation.id, role="user", content=question))
    assistant_message = CustomerServiceMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        sources_json=json.dumps(meta_sources, ensure_ascii=False, default=str),
    )
    db.add(assistant_message)
    _touch_conversation(conversation)
    conversation_id_value = conversation.id
    message_id_value = assistant_message.id
    db.commit()
    release_session_connection(db)
    return {
        "conversation_id": conversation_id_value,
        "message_id": message_id_value,
        "intent": "clarify",
        "answer_type": "clarification",
        "confidence": "low",
        "uncertainty": "ambiguous_product",
        "needs_clarification": True,
        "anomalies": [],
        "suggested_followups": ["你可以直接给我 SKU，或者让我先列出某个类目的产品。"],
        "followups": ["你可以直接给我 SKU，或者让我先列出某个类目的产品。"],
        "warnings": [],
        "evidence": [],
        "agent_quality": agent_quality,
        "debug": {"intent": "clarify", "steps": [], "warnings": [], "anomalies": [], "raw_results": [], "agent_quality": agent_quality},
        "sku": None,
        "answer": answer,
        "sources": [],
        "actions": [],
        "results": [],
        "steps": [],
    }


def _make_title(question: str, sku: str | None) -> str:
    clean = re.sub(r"\s+", " ", question).strip()
    return clean[:20] or (sku or "客服会话")


def _stringify(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _safe_json(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _should_use_previous_result_skus(question: str) -> bool:
    from . import customer_dialogue_state

    return customer_dialogue_state.should_use_previous_result_skus(question)


def _assistant_turn_index(db: Session, conversation_id: str) -> int:
    return db.query(CustomerServiceMessage).filter(
        CustomerServiceMessage.conversation_id == conversation_id,
        CustomerServiceMessage.role == "assistant",
    ).count()


def _primary_sku_from_message_content(content: str | None) -> str | None:
    text = str(content or "")
    if not text:
        return None
    if not any(word in text for word in ("首选", "优先推荐", "推荐", "建议")):
        return None
    match = SKU_RE.search(text)
    if not match:
        return None
    return match.group(0).upper()


