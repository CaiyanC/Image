from fastapi import APIRouter, Depends, Query, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.permission_constants import MANAGEMENT_GROUP_NAME
from ..core.security import get_user_groups, require_product_permission
from ..models.user import User
from ..schemas.product import (
    CheckSkusRequest, BatchCreateRequest,
)
from ..services import draft_service, operation_log_service

router = APIRouter(prefix="/api/products/drafts", tags=["product-drafts"])


def _is_management(user: User, db: Session) -> bool:
    for g in get_user_groups(db, user.id):
        if g["group_name"] == MANAGEMENT_GROUP_NAME:
            return True
    return False


def _draft_owner_scope(user: User, db: Session):
    return None if _is_management(user, db) else user.id


@router.get("")
def list_drafts(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    if _is_management(current_user, db):
        items, total = draft_service.get_all_drafts(db, skip, limit)
    else:
        items, total = draft_service.get_user_drafts(db, current_user.id, skip, limit)
    return {"items": items, "total": total}


@router.post("")
def create_draft(
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("create")),
    db: Session = Depends(get_db),
):
    draft = draft_service.create_draft(db, current_user.id, body)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="创建产品草稿",
        target_type="product_draft",
        target_id=draft["id"],
        target_name=draft.get("sku") or draft["id"],
        request_data=body,
        response_data={"draft_id": draft["id"], "sku": draft.get("sku")},
        request=request,
    )
    return draft


@router.post("/check-skus")
def check_skus(
    body: CheckSkusRequest,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    return draft_service.check_skus(db, body.skus, current_user.id)


@router.post("/batch")
def batch_import(
    body: BatchCreateRequest,
    request: Request,
    current_user: User = Depends(require_product_permission("create")),
    db: Session = Depends(get_db),
):
    items = [item.model_dump() for item in body.items]
    result = draft_service.batch_create_or_update(db, current_user.id, items)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="import",
        action_name="批量导入产品草稿",
        target_type="product_draft",
        target_id="batch",
        target_name=f"{len(items)} item(s)",
        request_data={"count": len(items), "skus": [item.get("sku") for item in items]},
        response_data=result,
        request=request,
    )
    return result


@router.get("/{draft_id}")
def get_draft(
    draft_id: str,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    draft = draft_service.get_draft_by_id(db, draft_id, _draft_owner_scope(current_user, db))
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft_service._draft_to_dict(draft)


@router.put("/{draft_id}")
def update_draft(
    draft_id: str,
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    draft = draft_service.update_draft(db, draft_id, body, _draft_owner_scope(current_user, db))
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="编辑产品草稿",
        target_type="product_draft",
        target_id=draft_id,
        target_name=draft.get("sku") or draft_id,
        request_data=body,
        response_data={"draft_id": draft_id, "sku": draft.get("sku")},
        request=request,
    )
    return draft


@router.delete("/{draft_id}")
def delete_draft(
    draft_id: str,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    draft = draft_service.get_draft_by_id(db, draft_id, _draft_owner_scope(current_user, db))
    target_name = draft.sku if draft and draft.sku else draft_id
    draft_service.delete_draft(db, draft_id, _draft_owner_scope(current_user, db))
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="删除产品草稿",
        target_type="product_draft",
        target_id=draft_id,
        target_name=target_name,
        response_data={"detail": "Draft deleted"},
        request=request,
    )
    return {"detail": "Draft deleted"}


@router.post("/{draft_id}/publish")
def publish_draft(
    draft_id: str,
    request: Request,
    current_user: User = Depends(require_product_permission("create")),
    db: Session = Depends(get_db),
):
    detail = draft_service.publish_draft(db, draft_id, _draft_owner_scope(current_user, db))
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="publish",
        action_name="发布产品草稿",
        target_type="product",
        target_id=detail.get("id", draft_id),
        target_name=detail.get("sku", draft_id),
        response_data={"draft_id": draft_id, "sku": detail.get("sku")},
        request=request,
    )
    return {"detail": "Draft published successfully"}
