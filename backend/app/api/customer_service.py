import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_user_permissions, require_permission
from ..models.user import User
from ..services import agent_action_service, customer_service_service, operation_log_service

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
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    result = await customer_service_service.ask_customer_service(
        db,
        user_id=current_user.id,
        question=body.question,
        sku=body.sku,
        conversation_id=body.conversation_id,
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
    return result


@router.post("/ask-stream")
async def ask_stream(
    body: CustomerServiceAskRequest,
    request: Request,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    async def event_stream():
        try:
            yield _sse("status", {"message": "agent_planning", "label": "正在理解问题并选择工具"})
            result = await customer_service_service.ask_customer_service(
                db,
                user_id=current_user.id,
                question=body.question,
                sku=body.sku,
                conversation_id=body.conversation_id,
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
            for chunk in _chunk_text(result.get("answer") or ""):
                yield _sse("answer_delta", {"text": chunk})
                await asyncio.sleep(0.01)
            yield _sse("done", {"ok": True})
        except Exception:
            logger.exception("customer service stream failed")
            yield _sse("error", {"message": _public_error_message()})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _public_error_message() -> str:
    return "智能客服暂时不可用，请稍后重试"


def _chunk_text(text: str, size: int = 3):
    for index in range(0, len(text), size):
        yield text[index:index + size]
