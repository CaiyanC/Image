import json
import uuid
from datetime import date
import re
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models.product_draft import ProductDraft
from ..models.product import Product
from .product_service import create_product, get_product_by_sku, get_product_detail


def _parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 40000 < value < 80000:
        return date.fromordinal(date(1899, 12, 30).toordinal() + int(value))
    value_str = str(value).strip()
    if re.match(r"^\d+(\.\d+)?$", value_str):
        serial = float(value_str)
        if 40000 < serial < 80000:
            return date.fromordinal(date(1899, 12, 30).toordinal() + int(serial))
    try:
        return date.fromisoformat(value_str)
    except (ValueError, TypeError):
        match = re.match(r"^\s*(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})\s*$", value_str)
        if not match:
            return None
        year, month, day = map(int, match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None


def _draft_to_dict(draft: ProductDraft) -> dict:
    dd = draft.draft_data or {}
    result = {
        "id": draft.id,
        "product_id": draft.product_id,
        "sku": draft.sku,
        "draft_data": dd,
        "status": draft.status,
        "created_by": draft.created_by,
        "created_at": str(draft.created_at) if draft.created_at else None,
        "updated_at": str(draft.updated_at) if draft.updated_at else None,
    }
    # Spread draft_data contents to top level for frontend compatibility
    for key in ("product_name_cn", "product_name_en", "barcode", "brand", "series",
                "category", "product_level", "launch_date", "lifecycle_status",
                "person_in_charge"):
        if key in dd:
            result[key] = dd[key]
    # Sub-objects: stored as "specs"/"business"/"content" in draft_data
    for stored_key, flat_key in (("specs", "specs_data"), ("business", "business_data"),
                                  ("content", "content_data"), ("media", "media_data"),
                                  ("prompts", "prompts_data")):
        if stored_key in dd:
            result[flat_key] = dd[stored_key]
            result[stored_key] = dd[stored_key]
    # QA pass-through
    for key in ("qa_items", "qa_negative"):
        if key in dd:
            result[key] = dd[key]
    return result


def _build_draft_data(data: dict) -> dict:
    """Build draft_data dict from flat frontend payload."""
    if "draft_data" in data and isinstance(data.get("draft_data"), dict) and data["draft_data"]:
        return data["draft_data"]
    dd = {}
    for key in ("product_name_cn", "product_name_en", "barcode", "brand", "series",
                "category", "product_level", "launch_date", "lifecycle_status",
                "person_in_charge"):
        if key in data and data[key] is not None:
            dd[key] = data[key]
    for flat_key, stored_key in (("specs_data", "specs"), ("business_data", "business"),
                                  ("content_data", "content"), ("media_data", "media"),
                                  ("prompts_data", "prompts")):
        if flat_key in data and data[flat_key] is not None:
            dd[stored_key] = data[flat_key]
    # QA and other direct pass-through keys
    for key in ("qa_items", "qa_negative"):
        if key in data and data[key] is not None:
            dd[key] = data[key]
    return dd


def get_user_drafts(db: Session, user_id: str, skip: int = 0, limit: int = 20):
    query = db.query(ProductDraft).filter(ProductDraft.created_by == str(user_id))
    total = query.count()
    drafts = query.order_by(ProductDraft.updated_at.desc()).offset(skip).limit(limit).all()
    return [_draft_to_dict(d) for d in drafts], total


def get_all_drafts(db: Session, skip: int = 0, limit: int = 20):
    query = db.query(ProductDraft)
    total = query.count()
    drafts = query.order_by(ProductDraft.updated_at.desc()).offset(skip).limit(limit).all()
    return [_draft_to_dict(d) for d in drafts], total


def get_draft_by_id(db: Session, draft_id: str, user_id = None) -> Optional[ProductDraft]:
    query = db.query(ProductDraft).filter(ProductDraft.id == draft_id)
    if user_id:
        query = query.filter(ProductDraft.created_by == str(user_id))
    return query.first()


def create_draft(db: Session, user_id: str, data: dict) -> dict:
    draft = ProductDraft(
        product_id=data.get("product_id"),
        sku=data.get("sku"),
        draft_data=_build_draft_data(data),
        status=data.get("status", "draft"),
        created_by=str(user_id),
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _draft_to_dict(draft)


def update_draft(db: Session, draft_id: str, data: dict, user_id: str = None) -> dict:
    draft = get_draft_by_id(db, draft_id, user_id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    for key in ("product_id", "sku", "status"):
        if key in data and data[key] is not None:
            setattr(draft, key, data[key])

    new_dd = _build_draft_data(data)
    if new_dd:
        existing_dd = dict(draft.draft_data or {})
        existing_dd.update(new_dd)
        draft.draft_data = existing_dd

    db.commit()
    db.refresh(draft)
    return _draft_to_dict(draft)


def delete_draft(db: Session, draft_id: str, user_id: str = None):
    draft = get_draft_by_id(db, draft_id, user_id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    db.delete(draft)
    db.commit()


def publish_draft(db: Session, draft_id: str, user_id: str = None) -> dict:
    draft = get_draft_by_id(db, draft_id, user_id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    draft_data = draft.draft_data or {}
    sku = draft.sku or draft_data.get("sku", "").strip()
    if not sku:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Draft must have a valid SKU")

    existing_product = get_product_by_sku(db, sku)

    if existing_product:
        # Validate L2 required fields (except certification)
        from .product_service import _to_json_str, _validate_product_data
        _validate_product_data(draft_data)

        # Update existing product with draft data
        from ..models.product_content import ProductContent

        pid = existing_product.id
        product_fields = {
            "barcode", "product_name_cn", "product_name_en", "brand", "series",
            "category", "product_level", "lifecycle_status", "person_in_charge",
        }
        for key in product_fields:
            if key in draft_data and draft_data[key] is not None:
                setattr(existing_product, key, draft_data[key])
        if "launch_date" in draft_data:
            existing_product.launch_date = _parse_date(draft_data.get("launch_date"))

        if "specs" in draft_data:
            from ..models.product_specs import ProductSpecs
            specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == pid).first()
            sd = draft_data["specs"]
            if specs:
                for k in ("size_info", "capacity", "gross_weight_g", "body_material",
                          "color", "surface_finish", "heat_source", "power",
                          "technical_advantages", "usage_instruction"):
                    if k in sd:
                        v = sd[k]
                        if k in ("size_info", "capacity", "technical_advantages"):
                            setattr(specs, k, _to_json_str(v))
                        else:
                            setattr(specs, k, v)
            else:
                from ..models.product_specs import ProductSpecs as PS
                db.add(PS(product_id=pid,
                    size_info=_to_json_str(sd.get("size_info")),
                    capacity=_to_json_str(sd.get("capacity")),
                    gross_weight_g=sd.get("gross_weight_g"),
                    body_material=sd.get("body_material"),
                    color=sd.get("color"),
                    surface_finish=sd.get("surface_finish"),
                    heat_source=sd.get("heat_source"),
                    power=sd.get("power"),
                    technical_advantages=_to_json_str(sd.get("technical_advantages")),
                    usage_instruction=sd.get("usage_instruction"),
                ))

        if "business" in draft_data:
            from ..models.product_business import ProductBusiness as PB
            biz = db.query(PB).filter(PB.product_id == pid).first()
            bd = draft_data["business"]
            if biz:
                for k in ("top_selling_points", "target_audience", "positioning",
                          "price_positioning", "emotional_value", "usage_scenarios",
                          "competitor_benchmark"):
                    if k in bd:
                        if k in ("top_selling_points", "usage_scenarios", "competitor_benchmark"):
                            setattr(biz, k, _to_json_str(bd[k]))
                        else:
                            setattr(biz, k, bd[k])
            else:
                db.add(PB(product_id=pid,
                    top_selling_points=_to_json_str(bd.get("top_selling_points")),
                    target_audience=bd.get("target_audience"),
                    positioning=bd.get("positioning"),
                    price_positioning=bd.get("price_positioning"),
                    emotional_value=bd.get("emotional_value"),
                    usage_scenarios=_to_json_str(bd.get("usage_scenarios")),
                    competitor_benchmark=_to_json_str(bd.get("competitor_benchmark")),
                ))

        if "content" in draft_data:
            from ..models.product_content import ProductContent as PC
            content = db.query(PC).filter(PC.product_id == pid).first()
            cd = draft_data["content"]
            if content:
                for k in ("title_en", "title_cn", "long_description_en", "long_description_cn",
                          "long_description_ja", "search_keywords", "amazon_title", "website_title",
                          "bullet_points", "a_plus_content", "listing_cn", "listing_en", "listing_ja"):
                    if k in cd:
                        if k in ("search_keywords", "bullet_points"):
                            setattr(content, k, _to_json_str(cd[k]))
                        else:
                            setattr(content, k, cd[k])
            else:
                db.add(PC(product_id=pid,
                    title_en=cd.get("title_en"), title_cn=cd.get("title_cn"),
                    long_description_en=cd.get("long_description_en"),
                    long_description_cn=cd.get("long_description_cn"),
                    long_description_ja=cd.get("long_description_ja"),
                    search_keywords=_to_json_str(cd.get("search_keywords")),
                    amazon_title=cd.get("amazon_title"), website_title=cd.get("website_title"),
                    bullet_points=_to_json_str(cd.get("bullet_points")),
                    a_plus_content=cd.get("a_plus_content"),
                    listing_cn=cd.get("listing_cn"), listing_en=cd.get("listing_en"),
                    listing_ja=cd.get("listing_ja"),
                ))

        # QA items - delete old and insert new
        from ..models.product_qa import ProductQa, ProductQaNegative
        db.query(ProductQa).filter(ProductQa.product_id == pid).delete()
        for qa in (draft_data.get("qa_items") or []):
            if qa.get("question") or qa.get("answer"):
                db.add(ProductQa(product_id=pid, question=qa.get("question", ""),
                    answer=qa.get("answer", ""), tags=qa.get("tags"), priority=qa.get("priority")))

        # QA negative
        qa_neg = draft_data.get("qa_negative") or {}
        db.query(ProductQaNegative).filter(ProductQaNegative.product_id == pid).delete()
        if qa_neg.get("high_freq_negative_words") or qa_neg.get("response_tone"):
            db.add(ProductQaNegative(product_id=pid,
                high_freq_negative_words=qa_neg.get("high_freq_negative_words"),
                response_tone=qa_neg.get("response_tone"), priority=qa_neg.get("priority")))

        # Product prompts - delete old and insert new
        from ..models.product_prompts import ProductPrompts
        db.query(ProductPrompts).filter(ProductPrompts.product_id == pid).delete()
        prompts_raw = draft_data.get("prompts") or []
        if isinstance(prompts_raw, dict):
            prompts = prompts_raw.get("prompts") or []
        else:
            prompts = prompts_raw if isinstance(prompts_raw, list) else []
        for p in prompts:
            if isinstance(p, dict) and p.get("prompt_text"):
                db.add(ProductPrompts(product_id=pid, sku=existing_product.sku,
                    prompt_name=p.get("prompt_name"), prompt_type=p.get("prompt_type"),
                    prompt_text=p.get("prompt_text"), version=p.get("version")))

        # Sync M2M associations from draft data
        from .product_service import sync_product_m2m
        sync_product_m2m(db, pid, draft_data)

        db.delete(draft)
        db.commit()
        return get_product_detail(db, sku)

    # New product: create from draft data
    draft_data["sku"] = sku
    product = create_product(db, draft_data, creator_id=user_id or draft.created_by)
    db.delete(draft)
    db.commit()
    return get_product_detail(db, product.sku)


def check_skus(db: Session, skus: list[str], user_id: str) -> dict:
    existing = {}

    for sku in skus:
        draft = db.query(ProductDraft).filter(
            ProductDraft.sku == sku,
            ProductDraft.created_by == str(user_id),
        ).order_by(ProductDraft.updated_at.desc()).first()

        if draft:
            existing[sku] = {
                "source": "draft",
                "id": draft.id,
                "sku": draft.sku,
                "draft_data": draft.draft_data or {},
                "status": draft.status,
            }
            continue

        product = get_product_by_sku(db, sku)
        if product:
            existing[sku] = {
                "source": "product",
                "id": product.id,
                "sku": product.sku,
                "product_name_cn": product.product_name_cn,
                "product_name_en": product.product_name_en,
                "brand": product.brand,
                "category": product.category,
                "product_level": product.product_level,
                "lifecycle_status": product.lifecycle_status,
                "person_in_charge": product.person_in_charge,
                "active_flag": product.active_flag,
            }
            continue

    missing = [s for s in skus if s not in existing]
    return {"existing": existing, "missing": missing}


def batch_create_or_update(db: Session, user_id: str, items: list[dict]) -> dict:
    created = 0
    updated = 0
    skipped = 0
    ids = []

    for item in items:
        sku = item.get("sku", "").strip()
        if not sku:
            skipped += 1
            continue

        existing_draft = db.query(ProductDraft).filter(
            ProductDraft.sku == sku,
            ProductDraft.created_by == str(user_id),
        ).first()

        draft_data = {
            "product_name_cn": item.get("product_name_cn"),
            "product_name_en": item.get("product_name_en"),
            "barcode": item.get("barcode"),
            "brand": item.get("brand"),
            "series": item.get("series"),
            "category": item.get("category"),
            "product_level": item.get("product_level"),
            "launch_date": item.get("launch_date"),
            "lifecycle_status": item.get("lifecycle_status"),
            "person_in_charge": item.get("person_in_charge"),
            "specs": item.get("specs_data"),
            "business": item.get("business_data"),
            "content": item.get("content_data"),
        }

        if existing_draft:
            existing_draft.draft_data = draft_data
            ids.append(existing_draft.id)
            updated += 1
        else:
            new_draft = ProductDraft(
                sku=sku,
                draft_data=draft_data,
                status="draft",
                created_by=str(user_id),
            )
            db.add(new_draft)
            db.flush()
            ids.append(new_draft.id)
            created += 1

    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "ids": ids}
