import json
import re

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models.knowledge_base import CustomerServiceConversation, CustomerServiceMessage
from ..models.product import Product
from ..models.product_qa import ProductQa, ProductQaNegative
from . import (
    customer_enterprise_guardrail_service,
    customer_agent_intent_service,
    customer_agent_quality_service,
    customer_agent_runtime_service,
    customer_agent_service,
    dmxapi_service,
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
) -> dict:
    user_id = str(user_id)
    question = question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="问题不能为空")

    agent_result = customer_enterprise_guardrail_service.evaluate_question(question)
    if agent_result:
        agent_result = _normalize_agent_result(agent_result)
        agent_result = _attach_agent_quality(agent_result, question)
        conversation = _get_or_create_conversation(db, user_id, question, agent_result.get("sku"), conversation_id)
        db.add(CustomerServiceMessage(
            conversation_id=conversation.id,
            role="user",
            content=question,
            sku=agent_result.get("sku"),
        ))
        assistant_message = CustomerServiceMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=agent_result["answer"],
            sku=agent_result.get("sku"),
            sources_json=json.dumps(_sources_with_result_context(agent_result), ensure_ascii=False, default=str),
        )
        db.add(assistant_message)
        _touch_conversation(conversation, agent_result.get("sku"))
        db.commit()
        return {
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
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
            "sources": agent_result.get("sources") or [],
            "actions": agent_result.get("actions") or [],
            "results": agent_result.get("results") or [],
            "steps": agent_result.get("steps") or [],
        }

    previous_result_skus = _latest_result_skus(db, conversation_id, user_id)
    contextual_previous_result_skus = previous_result_skus if _should_use_previous_result_skus(question) else []
    conversation_history = _build_conversation_history(db, conversation_id, user_id)
    contextual_conversation_history = conversation_history
    agent_result = await _try_named_product_shortcut(db, user_id=user_id, question=question)
    if not agent_result:
        agent_result = await customer_agent_runtime_service.process_agent_request(
            db,
            user_id=user_id,
            question=question,
            sku=None,
            previous_result_skus=contextual_previous_result_skus,
            conversation_history=contextual_conversation_history,
            feedback_lessons=_build_feedback_lessons(db, user_id),
        )
    if _should_retry_with_deterministic_agent(agent_result):
        retry_result = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=None,
            previous_result_skus=contextual_previous_result_skus,
        )
        if retry_result and retry_result.get("results"):
            agent_result = retry_result
    if not agent_result:
        agent_result = await customer_agent_intent_service.process_intent_request(
            db,
            user_id=user_id,
            question=question,
            sku=None,
            previous_result_skus=contextual_previous_result_skus,
        )
    if not agent_result:
        agent_result = customer_agent_service.try_numeric_english_name_query(db, question)
    if not agent_result:
        agent_result = customer_agent_service.process_agent_request(
            db,
            user_id=user_id,
            question=question,
            sku=None,
        )
    if agent_result:
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
        assistant_message = CustomerServiceMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=agent_result["answer"],
            sku=agent_result.get("sku"),
            sources_json=json.dumps(_sources_with_result_context(agent_result), ensure_ascii=False, default=str),
        )
        db.add(assistant_message)
        _touch_conversation(conversation, agent_result.get("sku"))
        db.commit()
        return {
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
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
            "sources": agent_result.get("sources") or [],
            "actions": agent_result.get("actions") or [],
            "results": agent_result.get("results") or [],
            "steps": agent_result.get("steps") or [],
        }

    resolved_sku = _resolve_sku(db, question, sku)
    if not resolved_sku:
        return _save_and_return_guidance(db, user_id, question, conversation_id)

    product = db.query(Product).filter(Product.sku == resolved_sku).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产品不存在")

    conversation = _get_or_create_conversation(db, user_id, question, resolved_sku, conversation_id)
    db.add(CustomerServiceMessage(
        conversation_id=conversation.id,
        role="user",
        content=question,
        sku=resolved_sku,
    ))

    context, sources = build_product_context(db, resolved_sku, question)
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
        answer = await dmxapi_service.chat_completion(db, messages)
    except Exception as exc:
        answer = f"聊天模型暂时不可用：{exc}"

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
    db.commit()

    return {
        "conversation_id": conversation.id,
        "message_id": assistant_message.id,
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


def _sources_with_result_context(agent_result: dict) -> list[dict]:
    sources = list(agent_result.get("sources") or [])
    sources.append({
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
    })
    if agent_result.get("steps"):
        sources.append({"type": "agent_steps", "label": "Agent执行过程", "steps": agent_result.get("steps")})
    result_skus = []
    for item in agent_result.get("results") or []:
        sku = item.get("sku") if isinstance(item, dict) else None
        if sku and sku not in result_skus and "," not in str(sku):
            result_skus.append(sku)
    if result_skus:
        sources.append({"type": "agent_context", "label": "上下文结果", "result_skus": result_skus, "count": len(result_skus)})
    return sources


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
    warnings = set(agent_result.get("warnings") or [])
    if "missing_product_results" in warnings:
        return True
    if agent_result.get("needs_clarification") and not agent_result.get("results"):
        return True
    return str(agent_result.get("confidence") or "").lower() == "low" and not agent_result.get("results")


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
    if len(products) == 1 and any(word in question for word in ("适合", "能不能", "可以", "能用", "带")):
        detail = product_service.get_product_detail(db, products[0].sku)
        return _named_product_context_result(question, detail)
    return None


def _products_named_in_question(db: Session, question: str) -> list[Product]:
    text = str(question or "")
    lower = text.lower()
    products = db.query(Product).all()
    matched: list[Product] = []
    for product in products:
        names = [product.product_name_cn, product.product_name_en]
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
        polished = await dmxapi_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=800,
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
    ).order_by(CustomerServiceMessage.created_at.desc()).limit(5).all()
    for message in messages:
        for source in _safe_json(message.sources_json, []):
            skus = source.get("result_skus") if isinstance(source, dict) else None
            if skus:
                return [str(sku) for sku in skus]
    return []


def _should_use_previous_result_skus(question: str) -> bool:
    text = str(question or "")
    explicit_refs = (
        "这些", "这几个", "这几款", "刚才", "上面", "上一轮", "前面",
        "他", "他的", "它", "它的", "该产品", "它们", "他们", "哪个", "哪款", "哪种", "这款", "这个", "那个", "其中",
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
    db.commit()
    return {
        "conversation_id": conversation.id,
        "message_id": assistant_message.id,
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
    prefix = f"{sku} " if sku else ""
    clean = re.sub(r"\s+", " ", question).strip()
    return (prefix + clean)[:80] or "客服会话"


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


