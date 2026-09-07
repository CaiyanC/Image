import json
import uuid
from datetime import date
import re
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..core.security import is_management_user
from ..models.product_draft import ProductDraft
from ..models.product import Product
from ..models.user import User
from .product_write_authorization import authorize_product_draft_publish
from .product_service import (
    create_product,
    get_product_by_sku,
    get_product_detail,
    invalidate_product_detail_cache,
    sync_product_to_vector_db,
)


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
    for key in ("qa_items", "qa_negative", "assets"):
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
    for key in ("specs", "business", "content", "media", "assets", "prompts"):
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


def get_draft_by_id(db: Session, draft_id: str, user_id = None, *, for_update: bool = False) -> Optional[ProductDraft]:
    query = db.query(ProductDraft).filter(ProductDraft.id == draft_id)
    if user_id:
        query = query.filter(ProductDraft.created_by == str(user_id))
    if for_update:
        query = query.populate_existing().with_for_update()
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


def _refresh_published_product(db: Session, sku: str) -> dict:
    """Make a published product immediately visible to detail and RAG readers."""
    normalized_sku = str(sku or "").strip().upper()
    # Invalidate before syncing as well as after it.  This covers both a
    # successful vector refresh and a provider failure, so readers never keep
    # serving the pre-publish detail snapshot.
    invalidate_product_detail_cache(db, normalized_sku)
    sync_product_to_vector_db(db, normalized_sku)
    invalidate_product_detail_cache(db, normalized_sku)
    return get_product_detail(db, normalized_sku)


def publish_draft(db: Session, draft_id: str, *, acting_user: User) -> dict:
    """Publish under the actor's authority, independently of draft ownership."""
    try:
        return _publish_draft(db, draft_id, acting_user=acting_user)
    except Exception:
        db.rollback()
        raise


def _publish_draft(db: Session, draft_id: str, *, acting_user: User) -> dict:
    if acting_user is None or not acting_user.is_active:
        raise HTTPException(status_code=403, detail="An active acting user is required")
    owner_scope = None if is_management_user(db, acting_user.id) else acting_user.id
    draft = get_draft_by_id(db, draft_id, owner_scope, for_update=True)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    draft_data = dict(draft.draft_data or {})
    sku = str(draft.sku or draft_data.get("sku") or "").strip()
    if not sku:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Draft must have a valid SKU")

    existing_product = get_product_by_sku(db, sku)
    # Accept the same aliases as product creation, while updating canonical
    # sections below. Do not modify the persisted draft before authorization.
    for flat, nested in (("specs_data", "specs"), ("business_data", "business"),
                         ("content_data", "content"), ("prompts_data", "prompts")):
        if flat in draft_data:
            draft_data[nested] = draft_data.pop(flat)
    asset_section_supplied = (
        "assets" in draft_data or "media_data" in draft_data or isinstance(draft_data.get("media"), dict)
    )
    draft_data = authorize_product_draft_publish(db, acting_user, sku, draft_data)

    if existing_product:
        # Validate L2 required fields (except certification)
        from .product_service import _to_json_str, _validate_product_data
        from .product_service import _build_detail
        validation_data = _build_detail(existing_product, db)
        for key, value in draft_data.items():
            if key in {"specs", "business", "content"} and isinstance(value, dict):
                validation_data[key] = {**(validation_data.get(key) or {}), **value}
            else:
                validation_data[key] = value
        _validate_product_data(validation_data)

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

        # A partial draft must not erase L4 relations it did not carry.  An
        # explicit section still replaces that section atomically, preserving
        # the existing draft-publish semantics for deliberate QA updates.
        if asset_section_supplied:
            from . import product_asset_sync_service
            product_asset_sync_service.sync_product_assets_from_snapshot_data(
                db, existing_product, draft_data["assets"]
            )

        # Persist the authorized plan; unchanged rows keep their audit history.
        from .product_write_authorization import apply_product_qa_write
        apply_product_qa_write(db, existing_product, draft_data)

        # Product prompts follow the same explicit-section rule.
        from ..models.product_prompts import ProductPrompts
        if "prompts" in draft_data:
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
        return _refresh_published_product(db, sku)

    # New product: create from draft data
    draft_data["sku"] = sku
    product = create_product(db, draft_data, creator_id=acting_user.id, commit=False)
    db.delete(draft)
    db.commit()
    return _refresh_published_product(db, product.sku)


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
