from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.product_operation_snapshot import ProductOperationSnapshot
from . import operation_log_service, product_service


def create_product_snapshot(
    db: Session,
    *,
    operation_log_id: str,
    operator_id: str,
    sku: str,
    action_type: str,
    before_data: dict | None,
    after_data: dict | None,
) -> ProductOperationSnapshot:
    snapshot = ProductOperationSnapshot(
        operation_log_id=str(operation_log_id),
        operator_id=str(operator_id),
        sku=str(sku),
        action_type=action_type,
        before_data=_clean_snapshot_data(before_data),
        after_data=_clean_snapshot_data(after_data),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def restore_product_snapshot(
    db: Session,
    snapshot_id: str,
    *,
    operator_id: str,
    request=None,
) -> dict[str, Any]:
    snapshot = db.query(ProductOperationSnapshot).filter(ProductOperationSnapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Product snapshot not found")
    if snapshot.restored_at:
        raise HTTPException(status_code=400, detail="Product snapshot already restored")

    target_data = snapshot.before_data
    current_exists = product_service.get_product_by_sku(db, snapshot.sku) is not None
    current_data = _safe_product_detail(db, snapshot.sku) if current_exists else None

    if target_data:
        if current_exists:
            product_service.delete_product(db, snapshot.sku)
        product = product_service.create_product(db, _payload_from_detail(target_data), creator_id=operator_id)
        restored_sku = product.sku
        restored_to = "before"
    else:
        if current_exists:
            product_service.delete_product(db, snapshot.sku)
        restored_sku = snapshot.sku
        restored_to = "deleted"

    snapshot.restored_at = datetime.now(timezone.utc)
    snapshot.restored_by = str(operator_id)
    db.commit()

    operation_log_service.log_operation(
        db,
        operator_id=operator_id,
        action_type="restore",
        action_name="恢复产品快照",
        target_type="product",
        target_id=snapshot.operation_log_id,
        target_name=snapshot.sku,
        request_data={"snapshot_id": snapshot.id, "restored_to": restored_to},
        response_data={
            "sku": restored_sku,
            "previous_current": current_data,
            "restored_data": target_data,
        },
        request=request,
    )
    return {"snapshot_id": snapshot.id, "sku": restored_sku, "restored_to": restored_to}


def _safe_product_detail(db: Session, sku: str) -> dict | None:
    try:
        return product_service.get_product_detail(db, sku)
    except HTTPException:
        return None


def _clean_snapshot_data(data: dict | None) -> dict | None:
    if not data:
        return None
    cleaned = dict(data)
    cleaned.pop("id", None)
    cleaned.pop("created_at", None)
    cleaned.pop("updated_at", None)
    for key in ("specs", "business", "content", "qa_negative"):
        if isinstance(cleaned.get(key), dict):
            cleaned[key] = dict(cleaned[key])
            cleaned[key].pop("id", None)
            cleaned[key].pop("product_id", None)
            cleaned[key].pop("created_at", None)
            cleaned[key].pop("updated_at", None)
    for key in ("qa_items", "media", "prompts"):
        if isinstance(cleaned.get(key), list):
            items = []
            for item in cleaned[key]:
                if isinstance(item, dict):
                    copy = dict(item)
                    copy.pop("id", None)
                    copy.pop("product_id", None)
                    copy.pop("created_at", None)
                    copy.pop("updated_at", None)
                    items.append(copy)
            cleaned[key] = items
    return cleaned


def _payload_from_detail(detail: dict) -> dict:
    payload = dict(detail)
    for key in ("id", "created_at", "updated_at"):
        payload.pop(key, None)
    return payload
