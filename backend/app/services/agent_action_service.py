import json
import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from ..models.agent_action import AgentAction
from ..models.product import Product
from ..models.product_business import ProductBusiness
from ..models.product_content import ProductContent
from ..models.product_qa import ProductQa, ProductQaNegative
from ..models.product_specs import ProductSpecs
from . import operation_log_service, product_service


UPDATE_PERMISSION = "product.edit"
DELETE_PERMISSION = "product.delete"


@dataclass(frozen=True)
class FieldSpec:
    section: str
    field: str
    label: str
    target_type: str
    model: type


FIELD_SPECS: dict[str, FieldSpec] = {
    "product.product_name_cn": FieldSpec("product", "product_name_cn", "名称", "product", Product),
    "product.brand": FieldSpec("product", "brand", "品牌", "product", Product),
    "product.series": FieldSpec("product", "series", "系列", "product", Product),
    "product.category": FieldSpec("product", "category", "类目", "product", Product),
    "product.sub_category": FieldSpec("product", "sub_category", "子类目", "product", Product),
    "product.product_level": FieldSpec("product", "product_level", "等级", "product", Product),
    "product.lifecycle_status": FieldSpec("product", "lifecycle_status", "生命周期", "product", Product),
    "product.person_in_charge": FieldSpec("product", "person_in_charge", "负责人", "product", Product),
    "product.quality_note": FieldSpec("product", "quality_note", "品质情况", "product", Product),
    "product.status_note": FieldSpec("product", "status_note", "备注", "product", Product),
    "specs.capacity": FieldSpec("specs", "capacity", "容量", "product_specs", ProductSpecs),
    "specs.gross_weight_g": FieldSpec("specs", "gross_weight_g", "重量", "product_specs", ProductSpecs),
    "specs.body_material": FieldSpec("specs", "body_material", "材质", "product_specs", ProductSpecs),
    "specs.color": FieldSpec("specs", "color", "颜色", "product_specs", ProductSpecs),
    "specs.surface_finish": FieldSpec("specs", "surface_finish", "表面工艺", "product_specs", ProductSpecs),
    "specs.heat_source": FieldSpec("specs", "heat_source", "热源", "product_specs", ProductSpecs),
    "specs.power": FieldSpec("specs", "power", "功率", "product_specs", ProductSpecs),
    "specs.technical_advantages": FieldSpec("specs", "technical_advantages", "技术优势", "product_specs", ProductSpecs),
    "specs.usage_instruction": FieldSpec("specs", "usage_instruction", "使用说明", "product_specs", ProductSpecs),
    "business.top_selling_points": FieldSpec("business", "top_selling_points", "卖点", "product_business", ProductBusiness),
    "business.target_audience": FieldSpec("business", "target_audience", "目标人群", "product_business", ProductBusiness),
    "business.positioning": FieldSpec("business", "positioning", "定位", "product_business", ProductBusiness),
    "business.price_positioning": FieldSpec("business", "price_positioning", "价格定位", "product_business", ProductBusiness),
    "business.emotional_value": FieldSpec("business", "emotional_value", "情绪价值", "product_business", ProductBusiness),
    "business.usage_scenarios": FieldSpec("business", "usage_scenarios", "使用场景", "product_business", ProductBusiness),
    "business.competitor_benchmark": FieldSpec("business", "competitor_benchmark", "竞品信息", "product_business", ProductBusiness),
    "content.title_cn": FieldSpec("content", "title_cn", "中文标题", "product_content", ProductContent),
    "content.title_en": FieldSpec("content", "title_en", "英文标题", "product_content", ProductContent),
    "content.long_description_cn": FieldSpec("content", "long_description_cn", "中文描述", "product_content", ProductContent),
    "content.long_description_en": FieldSpec("content", "long_description_en", "英文描述", "product_content", ProductContent),
    "content.search_keywords": FieldSpec("content", "search_keywords", "关键词", "product_content", ProductContent),
    "qa.question": FieldSpec("qa", "question", "QA 问题", "product_qa", ProductQa),
    "qa.answer": FieldSpec("qa", "answer", "QA 答案", "product_qa", ProductQa),
    "qa_negative.high_freq_negative_words": FieldSpec("qa_negative", "high_freq_negative_words", "差评关键词", "product_qa_negative", ProductQaNegative),
    "qa_negative.response_tone": FieldSpec("qa_negative", "response_tone", "差评应答口径", "product_qa_negative", ProductQaNegative),
}

FIELD_ALIASES = {
    "名称": "product.product_name_cn",
    "品牌": "product.brand",
    "系列": "product.series",
    "类目": "product.category",
    "等级": "product.product_level",
    "生命周期": "product.lifecycle_status",
    "负责人": "product.person_in_charge",
    "品质": "product.quality_note",
    "品质情况": "product.quality_note",
    "坏损": "product.quality_note",
    "备注": "product.status_note",
    "容量": "specs.capacity",
    "重量": "specs.gross_weight_g",
    "毛重": "specs.gross_weight_g",
    "材质": "specs.body_material",
    "颜色": "specs.color",
    "表面工艺": "specs.surface_finish",
    "热源": "specs.heat_source",
    "功率": "specs.power",
    "技术优势": "specs.technical_advantages",
    "使用说明": "specs.usage_instruction",
    "卖点": "business.top_selling_points",
    "目标人群": "business.target_audience",
    "定位": "business.positioning",
    "价格定位": "business.price_positioning",
    "情绪价值": "business.emotional_value",
    "使用场景": "business.usage_scenarios",
    "竞品信息": "business.competitor_benchmark",
    "标题": "content.title_cn",
    "关键词": "content.search_keywords",
    "QA问题": "qa.question",
    "QA答案": "qa.answer",
}


def resolve_field_path(label_or_path: str) -> str | None:
    cleaned = (label_or_path or "").strip()
    if cleaned in FIELD_SPECS:
        return cleaned
    return FIELD_ALIASES.get(cleaned)


def create_update_field_action(
    db: Session,
    *,
    created_by: str,
    sku: str,
    field_path: str,
    new_value: Any,
    target_id: str | None = None,
) -> AgentAction:
    spec = _require_field_spec(field_path)
    current_value = _read_current_value(db, sku, spec, target_id)
    proposed_value = _normalize_proposed_value(spec, current_value, new_value)
    action = AgentAction(
        action_type="update_field",
        sku=sku,
        target_type=spec.target_type,
        target_id=target_id,
        field_path=field_path,
        field_label=spec.label,
        original_value_json=_dumps(current_value),
        proposed_value_json=_dumps(proposed_value),
        status="pending",
        created_by=str(created_by),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def create_clear_field_action(
    db: Session,
    *,
    created_by: str,
    sku: str,
    field_path: str,
    target_id: str | None = None,
) -> AgentAction:
    action = create_update_field_action(
        db,
        created_by=created_by,
        sku=sku,
        field_path=field_path,
        new_value="",
        target_id=target_id,
    )
    action.action_type = "delete_info"
    db.commit()
    db.refresh(action)
    return action


def create_delete_qa_action(db: Session, *, created_by: str, sku: str, qa_id: str) -> AgentAction:
    qa = db.query(ProductQa).filter(ProductQa.id == qa_id).first()
    if not qa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QA item not found")
    action = AgentAction(
        action_type="delete_info",
        sku=sku,
        target_type="product_qa",
        target_id=qa_id,
        field_path=None,
        field_label="QA",
        original_value_json=_dumps({"question": qa.question, "answer": qa.answer}),
        proposed_value_json=_dumps(None),
        status="pending",
        created_by=str(created_by),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def create_delete_product_action(db: Session, *, created_by: str, sku: str) -> AgentAction:
    detail = product_service.get_product_detail(db, sku)
    action = AgentAction(
        action_type="delete_product",
        sku=sku,
        target_type="product",
        target_id=str(detail["id"]),
        field_path=None,
        field_label="整个产品",
        original_value_json=_dumps(_delete_preview(detail)),
        proposed_value_json=_dumps(None),
        status="pending",
        created_by=str(created_by),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def confirm_action(
    db: Session,
    *,
    action_id: str,
    confirmed_by: str,
    permissions: set[str],
    request: Request | None = None,
) -> dict:
    action = _get_pending_action(db, action_id)
    if action.action_type == "delete_product":
        _require_permission(permissions, DELETE_PERMISSION)
    else:
        _require_permission(permissions, UPDATE_PERMISSION)

    try:
        result = _execute_action(db, action)
        action.status = "confirmed"
        action.confirmed_by = str(confirmed_by)
        action.result_json = _dumps(result)
        db.commit()
        _log_action(db, action, confirmed_by, request, status_value="success")
        return serialize_action(action)
    except _StaleAction as exc:
        action.status = "stale"
        action.confirmed_by = str(confirmed_by)
        action.result_json = _dumps({"current_value": exc.current_value})
        db.commit()
        return {**serialize_action(action), "current_value": exc.current_value}
    except Exception as exc:
        db.rollback()
        action = db.query(AgentAction).filter(AgentAction.id == action_id).first()
        if action:
            action.status = "failed"
            action.confirmed_by = str(confirmed_by)
            action.error_message = str(exc)
            db.commit()
            _log_action(db, action, confirmed_by, request, status_value="failed", error_message=str(exc))
        raise


def cancel_action(db: Session, action_id: str, *, cancelled_by: str) -> dict:
    action = db.query(AgentAction).filter(AgentAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent action not found")
    if action.status == "confirmed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmed action cannot be cancelled")
    if action.status == "cancelled":
        return serialize_action(action)
    action.status = "cancelled"
    action.confirmed_by = str(cancelled_by)
    db.commit()
    db.refresh(action)
    return serialize_action(action)


def serialize_action(action: AgentAction) -> dict:
    return {
        "id": action.id,
        "action_type": action.action_type,
        "sku": action.sku,
        "target_type": action.target_type,
        "target_id": action.target_id,
        "field_path": action.field_path,
        "field_label": action.field_label,
        "original_value": action.original_value,
        "proposed_value": action.proposed_value,
        "status": action.status,
        "result": action.result,
        "error_message": action.error_message,
        "created_at": str(action.created_at) if action.created_at else None,
        "updated_at": str(action.updated_at) if action.updated_at else None,
    }


def _execute_action(db: Session, action: AgentAction) -> dict:
    if action.action_type == "delete_info" and action.target_type == "product_qa":
        product_service.delete_qa_item(db, action.target_id)
        _mark_product_needs_vector_sync(db, action.sku)
        return {"sku": action.sku, "deleted": action.target_type, "target_id": action.target_id}
    if action.action_type in {"update_field", "delete_info"} and action.field_path:
        spec = _require_field_spec(action.field_path)
        current_value = _read_current_value(db, action.sku, spec, action.target_id)
        if _normal_value(current_value) != _normal_value(action.original_value):
            raise _StaleAction(current_value)
        _write_field(db, action.sku, spec, action.proposed_value, action.target_id)
        _mark_product_needs_vector_sync(db, action.sku)
        return {
            "sku": action.sku,
            "field_path": action.field_path,
            "old_value": action.original_value,
            "new_value": action.proposed_value,
        }
    if action.action_type == "delete_product":
        product_service.delete_product(db, action.sku)
        return {"sku": action.sku, "deleted": "product"}
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action")


def _write_field(db: Session, sku: str, spec: FieldSpec, value: Any, target_id: str | None) -> None:
    if spec.section == "product":
        product_service.update_product(db, sku, {spec.field: value})
    elif spec.section == "specs":
        product_service.update_product_specs(db, sku, {spec.field: value})
    elif spec.section == "business":
        product_service.update_product_business(db, sku, {spec.field: value})
    elif spec.section == "content":
        product_service.update_product_content(db, sku, {spec.field: value})
    elif spec.section == "qa":
        if not target_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="QA target_id is required")
        product_service.update_qa_item(db, target_id, {spec.field: value})
    elif spec.section == "qa_negative":
        product_service.upsert_qa_negative(db, sku, {spec.field: value})


def _read_current_value(db: Session, sku: str, spec: FieldSpec, target_id: str | None = None) -> Any:
    product = product_service.get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if spec.section == "product":
        return getattr(product, spec.field)
    if spec.section == "qa":
        if not target_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="QA target_id is required")
        item = db.query(ProductQa).filter(ProductQa.id == target_id, ProductQa.product_id == product.id).first()
    elif spec.section == "qa_negative":
        item = db.query(ProductQaNegative).filter(ProductQaNegative.product_id == product.id).first()
    else:
        item = db.query(spec.model).filter(spec.model.product_id == product.id).first()
    if not item:
        return None
    return getattr(item, spec.field)


def _get_pending_action(db: Session, action_id: str) -> AgentAction:
    action = db.query(AgentAction).filter(AgentAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent action not found")
    if action.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent action is not pending")
    return action


def _require_field_spec(field_path: str) -> FieldSpec:
    spec = FIELD_SPECS.get(field_path)
    if not spec:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Field not allowed: {field_path}")
    return spec


def _require_permission(permissions: set[str], permission_key: str) -> None:
    if permission_key not in permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission required: {permission_key}")


def _mark_product_needs_vector_sync(db: Session, sku: str) -> None:
    product = product_service.get_product_by_sku(db, sku)
    if product:
        product.sync_flag = False
        db.commit()


def _log_action(
    db: Session,
    action: AgentAction,
    operator_id: str,
    request: Request | None,
    *,
    status_value: str,
    error_message: str | None = None,
) -> None:
    operation_log_service.log_operation(
        db,
        operator_id=operator_id,
        action_type=action.action_type,
        action_name="Agent 确认执行",
        target_type=action.target_type,
        target_id=action.target_id or action.sku,
        target_name=action.sku,
        request_data=serialize_action(action),
        response_data=action.result,
        status=status_value,
        error_message=error_message,
        request=request,
    )


def _delete_preview(detail: dict) -> dict:
    return {
        "id": str(detail.get("id")) if detail.get("id") is not None else None,
        "sku": detail.get("sku"),
        "product_name_cn": detail.get("product_name_cn"),
        "will_delete": {
            "product": True,
            "specs": bool(detail.get("specs")),
            "business": bool(detail.get("business")),
            "content": bool(detail.get("content")),
            "qa_count": len(detail.get("qa_items") or []),
            "qa_negative": bool(detail.get("qa_negative")),
            "media_count": len(detail.get("media") or []),
            "prompt_count": len(detail.get("prompts") or []),
            "channels_count": len(detail.get("channels") or []),
            "regions_count": len(detail.get("regions") or []),
            "certifications_count": len(detail.get("certifications") or []),
            "keywords_count": len(detail.get("keywords") or []),
        },
    }


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _normal_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _normalize_proposed_value(spec: FieldSpec, current_value: Any, new_value: Any) -> Any:
    if spec.section == "specs" and spec.field == "capacity":
        return _normalize_capacity_update(current_value, new_value)
    return new_value


def _normalize_capacity_update(current_value: Any, new_value: Any) -> Any:
    parsed = _parse_json_value(current_value)
    requested_label, requested_value = _split_capacity_request(new_value)
    if isinstance(parsed, dict):
        updated = dict(parsed)
        value_key = "value" if "value" in updated else "label"
        if requested_label and "label" in updated and str(updated.get("label") or "").strip() != requested_label:
            value_key = "value"
        updated[value_key] = requested_value
        return updated
    if isinstance(parsed, list) and parsed and all(isinstance(item, dict) for item in parsed):
        updated_items = [dict(item) for item in parsed]
        matched_indexes = [
            index for index, item in enumerate(updated_items)
            if requested_label and str(item.get("label") or "").strip() == requested_label
        ]
        if matched_indexes:
            for index in matched_indexes:
                updated_items[index]["value"] = requested_value
            return updated_items
        if len(updated_items) == 1:
            updated_items[0]["value"] = requested_value
            return updated_items
        return new_value
    return new_value


def _parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _split_capacity_request(value: Any) -> tuple[str | None, Any]:
    if isinstance(value, dict):
        label = str(value.get("label") or "").strip() or None
        return label, value.get("value") or value.get("label") or ""
    text = str(value or "").strip()
    match = re.match(r"^([\u4e00-\u9fffA-Za-z]+)\s*[:：]\s*(.+)$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, value


class _StaleAction(Exception):
    def __init__(self, current_value: Any):
        super().__init__("Current value changed")
        self.current_value = current_value
