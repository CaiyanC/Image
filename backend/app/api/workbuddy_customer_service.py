from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.rate_limit import enforce_rate_limit
from ..core.security import has_permission, require_permission, security
from ..models.user import User
from ..models.workbuddy_customer_service_token import WorkBuddyCustomerServiceToken
from ..services import (
    customer_llm_service,
    customer_listing_source,
    customer_perf_service,
    customer_pipeline_service,
    customer_service_service,
    operation_log_service,
    workbuddy_customer_knowledge_service,
    workbuddy_customer_service_connector,
)

router = APIRouter(prefix="/api/workbuddy/customer-service", tags=["workbuddy-customer-service"])


class ConnectorTokenCreateRequest(BaseModel):
    name: str = Field(default="WorkBuddy 客服连接", min_length=1, max_length=100)
    expires_in_days: int = Field(default=90, ge=1, le=365)
    allow_qa_write: bool = False


class ConnectorAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    sku: str | None = Field(default=None, max_length=100)
    conversation_id: str | None = Field(default=None, max_length=100)


SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SkuText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ConnectorSearchRequest(BaseModel):
    query: SearchText
    sku: SkuText | None = None
    limit: int = Field(default=5, ge=1, le=10)


class ConnectorProductSearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    limit: int = Field(default=5, ge=1, le=10)


class ConnectorQaDraftRequest(BaseModel):
    sku: SkuText
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    message_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)] | None = None
    confirmed: bool = Field(strict=True)


class ConnectorQaExportRequest(BaseModel):
    sku: SkuText
    include_unapproved: bool = Field(default=False, strict=True)


class ConnectorProductProfileRequest(BaseModel):
    sku: SkuText


class ConnectorQaRevisionRequest(BaseModel):
    sku: SkuText
    qa_id: UUID
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    confirmed: bool = Field(strict=True)


class ProductLinkRequest(BaseModel):
    sku: SkuText
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    enabled: bool = Field(default=True, strict=True)
    snapshot_text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=6000)] | None = None


class ProductLinkPreviewRequest(BaseModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


def _can_write_qa(db: Session, user: User) -> bool:
    return any(has_permission(db, user.id, key) for key in ("product.qa.manage", "product.edit"))


def _token_response(row: WorkBuddyCustomerServiceToken) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "token_prefix": row.token_prefix,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "last_used_at": row.last_used_at,
        "revoked_at": row.revoked_at,
        "allow_qa_write": row.token_prefix.startswith(workbuddy_customer_service_connector.QA_TOKEN_PREFIX),
    }


@router.post("/tokens")
def create_connector_token(
    body: ConnectorTokenCreateRequest,
    response: Response,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    if body.allow_qa_write and not _can_write_qa(db, current_user):
        raise HTTPException(status_code=403, detail="当前账号没有产品 QA 管理权限")
    now = datetime.now(timezone.utc)
    active_tokens = db.query(WorkBuddyCustomerServiceToken).filter(
        WorkBuddyCustomerServiceToken.user_id == current_user.id,
        WorkBuddyCustomerServiceToken.revoked_at.is_(None),
        WorkBuddyCustomerServiceToken.expires_at > now.replace(tzinfo=None),
    ).count()
    if active_tokens >= workbuddy_customer_service_connector.MAX_ACTIVE_TOKENS_PER_USER:
        raise HTTPException(status_code=409, detail="最多保留 5 个有效的 WorkBuddy 客服连接令牌，请先撤销旧令牌")
    row, token = workbuddy_customer_service_connector.issue_connector_token(
        db,
        user_id=current_user.id,
        name=body.name,
        expires_in_days=body.expires_in_days,
        allow_qa_write=body.allow_qa_write,
    )
    # The plaintext credential is returned once and is never persisted.
    return {**_token_response(row), "token": token}


@router.get("/tokens")
def list_connector_tokens(
    response: Response,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    rows = db.query(WorkBuddyCustomerServiceToken).filter(
        WorkBuddyCustomerServiceToken.user_id == current_user.id,
    ).order_by(WorkBuddyCustomerServiceToken.created_at.desc()).limit(20).all()
    return {"items": [_token_response(row) for row in rows]}


@router.delete("/tokens/{token_id}")
def revoke_connector_token(
    token_id: str,
    current_user: User = Depends(require_permission("ai.customer_service")),
    db: Session = Depends(get_db),
):
    row = db.query(WorkBuddyCustomerServiceToken).filter(
        WorkBuddyCustomerServiceToken.id == token_id,
        WorkBuddyCustomerServiceToken.user_id == current_user.id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="连接令牌不存在")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"id": row.id, "revoked": True}


def _current_connector_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    raw_token = credentials.credentials if credentials else ""
    if not raw_token.startswith((
        workbuddy_customer_service_connector.TOKEN_PREFIX,
        workbuddy_customer_service_connector.QA_TOKEN_PREFIX,
    )):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WorkBuddy 客服连接无效或已过期，请重新连接",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_hash = workbuddy_customer_service_connector.hash_connector_token(raw_token)
    row = db.query(WorkBuddyCustomerServiceToken).filter(
        WorkBuddyCustomerServiceToken.token_hash == token_hash,
    ).first()
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WorkBuddy 客服连接无效或已过期，请重新连接",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expires_at = workbuddy_customer_service_connector.as_utc(row.expires_at)
    if expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WorkBuddy 客服连接无效或已过期，请重新连接",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None or not user.is_active or not has_permission(db, user.id, "ai.customer_service"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WorkBuddy 客服连接无效或已过期，请重新连接",
            headers={"WWW-Authenticate": "Bearer"},
        )
    row.last_used_at = now
    db.commit()
    return user


def _safe_sources(result: dict) -> list[dict]:
    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    safe = []
    for source in sources:
        if not isinstance(source, dict) or source.get("type") == "agent_meta":
            continue
        source_type = str(source.get("source_type") or source.get("type") or "").strip()[:60]
        if not source_type:
            continue
        safe.append({
            "source_type": source_type,
            "sku": str(source.get("sku") or "").strip()[:100] or None,
            "source_id": str(source.get("source_id") or "").strip()[:100] or None,
            "evidence_id": str(source.get("evidence_id") or "").strip()[:100] or None,
            "title": str(source.get("source_title") or source.get("title") or source.get("label") or "").strip()[:120] or None,
            "section": str(source.get("source_section") or source.get("section") or "").strip()[:80] or None,
        })
    return safe


def _connector_answer(result: dict) -> dict:
    selected_skus = {
        str(sku).strip().upper() for sku in (result.get("result_skus") or []) if str(sku).strip()
    }
    sources = _safe_sources(result)
    if selected_skus:
        sources = [source for source in sources if not source["sku"] or source["sku"].upper() in selected_skus]
    else:
        sources = [source for source in sources if not source["sku"]]
    return {
        "answer": str(result.get("answer") or ""),
        "conversation_id": result.get("conversation_id"),
        "message_id": result.get("message_id"),
        "answer_type": result.get("answer_type"),
        "intent": result.get("intent"),
        "confidence": result.get("confidence"),
        "uncertainty": result.get("uncertainty"),
        "needs_clarification": bool(result.get("needs_clarification")),
        "suggested_followups": list(result.get("suggested_followups") or [])[:5],
        "sku": result.get("sku"),
        "result_skus": list(result.get("result_skus") or [])[:8],
        "sources": sources[:8],
    }


@router.post("/ask")
async def ask_customer_service(
    body: ConnectorAskRequest,
    request: Request,
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    if body.sku and body.sku.strip():
        workbuddy_customer_knowledge_service._active_product(db, body.sku.strip())
    enforce_rate_limit(
        user_id=current_user.id,
        scope="workbuddy_customer_service.ask",
        limit=30,
        window_seconds=60,
    )
    customer_perf_service.start_trace()
    governance_token = customer_llm_service.set_governed_customer_user(current_user)
    try:
        result = await customer_service_service.ask_customer_service(
            db,
            user_id=current_user.id,
            question=body.question,
            sku=body.sku,
            conversation_id=body.conversation_id,
            pipeline=customer_pipeline_service.WORKBUDDY_RAG_PIPELINE,
            server_selected_pipeline=True,
        )
    finally:
        customer_llm_service.reset_governed_customer_user(governance_token)
    response = _connector_answer(result)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="ask",
        action_name="WorkBuddy 智能客服问答",
        target_type="customer_service",
        target_id=str(response.get("conversation_id") or ""),
        target_name=response.get("sku") or "未选择产品",
        request_data={"question": body.question, "sku": body.sku, "channel": "workbuddy_connector"},
        response_data={"answer": response["answer"], "sources": response["sources"]},
        request=request,
    )
    return response


@router.post("/products/search")
def find_customer_products(
    body: ConnectorProductSearchRequest,
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.product_search", limit=60, window_seconds=60)
    return workbuddy_customer_knowledge_service.find_products(db, body.query, body.limit)


@router.put("/product-links")
def set_customer_product_link(
    body: ProductLinkRequest,
    request: Request,
    current_user: User = Depends(require_permission("product.edit")),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.link_mapping", limit=30, window_seconds=60)
    return workbuddy_customer_knowledge_service.set_product_link(
        db, url=body.url, sku=body.sku, enabled=body.enabled, user_id=current_user.id, request=request,
        snapshot_text=body.snapshot_text,
    )


@router.post("/product-links/preview")
async def preview_customer_product_link(
    body: ProductLinkPreviewRequest,
    current_user: User = Depends(require_permission("product.edit")),
):
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.link_preview", limit=10, window_seconds=60)
    identity = workbuddy_customer_knowledge_service.marketplace_item(body.url)
    if identity is None:
        raise HTTPException(status_code=422, detail="请填写支持的平台商品详情页长链接")
    return await customer_listing_source.fetch_listing_preview(*identity)


@router.post("/listings/search")
def search_customer_listings(
    body: ConnectorSearchRequest,
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.listing_search", limit=60, window_seconds=60)
    if body.sku is None:
        raise HTTPException(status_code=422, detail="请先选定商品 SKU")
    return workbuddy_customer_knowledge_service.search_listing_evidence(db, body.sku, body.query, body.limit)


@router.post("/knowledge/search")
async def search_customer_knowledge(
    body: ConnectorSearchRequest,
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.knowledge_search", limit=30, window_seconds=60)
    if body.sku is None:
        raise HTTPException(status_code=422, detail="请先选定商品 SKU，再查询同 SKU 问答")
    return await workbuddy_customer_knowledge_service.search_approved_qa(db, body.sku, body.query, body.limit)


@router.post("/qa-drafts")
def save_customer_qa_draft(
    body: ConnectorQaDraftRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    if not credentials.credentials.startswith(workbuddy_customer_service_connector.QA_TOKEN_PREFIX) or not _can_write_qa(db, current_user):
        raise HTTPException(status_code=403, detail="请使用有 QA 管理权限账号签发的 QA 录入令牌")
    if not body.confirmed:
        raise HTTPException(status_code=422, detail="请先确认 SKU、问题和答案，再保存 QA")
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.qa_draft", limit=20, window_seconds=60)
    return workbuddy_customer_knowledge_service.save_qa_draft(
        db, user_id=current_user.id, sku=body.sku, question=body.question,
        answer=body.answer, message_id=body.message_id, request=request,
    )


@router.post("/knowledge/export")
def export_customer_qa(
    body: ConnectorQaExportRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    if body.include_unapproved and (
        not credentials.credentials.startswith(workbuddy_customer_service_connector.QA_TOKEN_PREFIX)
        or not _can_write_qa(db, current_user)
    ):
        raise HTTPException(status_code=403, detail="导出待审核和未通过的问答须使用 QA 管理连接")
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.qa_export", limit=15, window_seconds=60)
    sku, count, document = workbuddy_customer_knowledge_service.export_product_qa(
        db, body.sku, include_unapproved=body.include_unapproved,
    )
    return Response(
        content=document,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(sku + '-QA.docx', safe='')}",
            "X-CaiYan-SKU": quote(sku, safe=""),
            "X-CaiYan-QA-Count": str(count),
        },
    )


@router.post("/products/profile")
def get_customer_product_profile(
    body: ConnectorProductProfileRequest,
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.product_profile", limit=30, window_seconds=60)
    return workbuddy_customer_knowledge_service.get_customer_product_profile(db, body.sku)


@router.post("/products/export")
def export_customer_product_profile(
    body: ConnectorProductProfileRequest,
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.product_export", limit=15, window_seconds=60)
    sku, count, document = workbuddy_customer_knowledge_service.export_customer_product_profile(db, body.sku)
    return Response(
        content=document,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(sku + '-profile.docx', safe='')}",
            "X-CaiYan-SKU": quote(sku, safe=""),
            "X-CaiYan-QA-Count": str(count),
        },
    )


@router.post("/qa-revisions")
def submit_customer_qa_revision(
    body: ConnectorQaRevisionRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: User = Depends(_current_connector_user),
    db: Session = Depends(get_db),
):
    if not credentials.credentials.startswith(workbuddy_customer_service_connector.QA_TOKEN_PREFIX) or not _can_write_qa(db, current_user):
        raise HTTPException(status_code=403, detail="当前连接没有提交 QA 修订的权限")
    if not body.confirmed:
        raise HTTPException(status_code=422, detail="请先确认要修订的 SKU、原问答和新答案")
    enforce_rate_limit(user_id=current_user.id, scope="workbuddy_customer_service.qa_revision", limit=20, window_seconds=60)
    return workbuddy_customer_knowledge_service.propose_qa_revision(
        db, user_id=current_user.id, sku=body.sku, qa_id=str(body.qa_id),
        answer=body.answer, reason=body.reason or None, request=request,
    )
