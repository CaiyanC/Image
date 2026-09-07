"""Authorization for product writes that carry media across API boundaries.

Call before any mutation, using the acting user (never the draft creator).
``authorize_product_replacement`` returns the payload that MUST be persisted;
it preserves governance metadata when unchanged media_data URLs are resubmitted.
Draft updates have partial-section semantics: use authorize_product_draft_publish
to merge omitted media sections before applying the replacement validator.
"""

import json
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..core.security import has_permission
from ..models.product import Product
from ..models.product_asset import ProductAsset
from ..models.product_media import ProductMedia
from ..models.product_qa import ProductQa, ProductQaNegative
from ..models.user import User
from . import product_asset_sync_service as asset_sync


REVIEW_FIELDS = {
    "status_tag", "review_status", "authorization_status", "asset_level", "media_level",
    "is_public", "ai_customer_usable", "ai_marketing_usable", "ai_reference_usable",
    "forbidden_usage", "is_latest_version", "quality_status", "quality_reason",
    "duplicate_status", "duplicate_of_asset_id", "is_real_product",
    "is_ai_generated", "is_competitor", "editable_flag",
}
IDENTITY_FIELDS = {"url", "thumbnail_url", "file_path", "file_url", "checksum_sha256"}


def _require(db, user, permission):
    if not has_permission(db, user.id, permission):
        raise HTTPException(status_code=403, detail=f"Permission required: {permission}")


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            pass
    return value


def _defaults(model):
    return {
        column.name: column.default.arg if column.default is not None and column.default.is_scalar else None
        for column in model.__table__.columns
        if column.name not in {"id", "sku", "product_id", "created_at", "updated_at"}
    }


def _record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _effective(model, payload):
    result = _defaults(model)
    result.update({key: value for key, value in payload.items() if key in result and value is not None})
    for field in ("tags", "tag_list"):
        if field in result:
            result[field] = _json(result[field]) or ({} if field == "tags" else [])
    return result


def _check_fields(db, user, before, after, defaults):
    # Changing the underlying file cannot inherit a different file's approval.
    identity_changed = any(before.get(key) != after.get(key) for key in IDENTITY_FIELDS)
    review_changed = any(
        before.get(key) != after.get(key)
        or (identity_changed and defaults.get(key) != after.get(key))
        for key in REVIEW_FIELDS if key in after
    )
    for field in ("tags", "tag_list"):
        old_tags, new_tags = _json(before.get(field)) or {}, _json(after.get(field)) or {}
        if old_tags != new_tags:
            _require(db, user, "tag.edit")
        old_risk = old_tags.get("risk_tags") if isinstance(old_tags, dict) else None
        new_risk = new_tags.get("risk_tags") if isinstance(new_tags, dict) else None
        if (old_risk or []) != (new_risk or []) or (identity_changed and new_risk):
            review_changed = True
    if review_changed:
        _require(db, user, "media.review")


def authorize_product_media_write(
    db: Session, user: User, payload: dict | None = None, *, current: ProductMedia | None = None,
) -> None:
    """Legacy create/update/delete; current must have been resolved under path SKU."""
    _require(db, user, "product.edit")
    _require(db, user, "media.upload")
    if payload is None:  # deletion does not change individual governance fields
        return
    defaults = _effective(ProductMedia, {})
    before = _effective(ProductMedia, _record(current)) if current is not None else defaults
    after = {**before, **{
        key: value for key, value in payload.items()
        if key in defaults and (value is not None or key == "tag_list")
    }}
    _check_fields(db, user, before, after, defaults)


class _AssetPreview:
    """Collect the existing media synchronizer's output without a DB or writes.

    Its initial scoped DELETE is intentionally a no-op: this collection is empty.
    Keeping projection in the actual synchronizer avoids divergent field defaults.
    """

    def __init__(self):
        self.rows = []

    def query(self, model):
        assert model is ProductAsset
        return self

    def filter(self, *criteria):
        return self

    def delete(self, **kwargs):
        return 0

    def add(self, row):
        self.rows.append(row)


def _source_identity(item):
    return tuple(item.get(key) for key in ("source_key", "url", "channel", "version_tag"))


def _legacy_contents(item: dict) -> dict:
    result = _defaults(ProductMedia)
    result.update({key: value for key, value in item.items() if key in result})
    result["tag_list"] = _json(result["tag_list"]) or []
    return result


def validate_legacy_media_replacement(db: Session, sku: str, payload: dict) -> list[dict]:
    """Return locked legacy records to preserve; list-valued media is read-only.

    IDs/timestamps are response metadata. When IDs or SKU bindings are supplied
    they must identify the same row; identity-free snapshots match by contents.
    """
    product = db.query(Product).filter(Product.sku == sku).with_for_update().first()
    records = [
        _record(row) for row in db.query(ProductMedia).filter(
            ProductMedia.product_id == product.id,
        ).populate_existing().with_for_update().all()
    ] if product else []
    if any(row["sku"] != sku for row in records):
        raise HTTPException(status_code=409, detail="Legacy media SKU binding is inconsistent")
    submitted = payload.get("media")
    if not isinstance(submitted, list):
        return records
    remaining = list(records)
    columns = set(ProductMedia.__table__.columns.keys())
    for item in submitted:
        if not isinstance(item, dict) or set(item) - columns:
            break
        candidate = next((row for row in remaining if (
            (not item.get("id") or str(item["id"]) == str(row["id"]))
            and item.get("sku", sku) == sku
            and str(item.get("product_id", row["product_id"])) == str(row["product_id"])
            and _legacy_contents(item) == _legacy_contents(row)
        )), None)
        if candidate is None:
            break
        remaining.remove(candidate)
    else:
        if not remaining:
            return records
    raise HTTPException(status_code=400, detail="Legacy media changes must use the /media dedicated API")


def _merge_media_sections(before: dict, updates: dict) -> dict:
    merged = dict(before)
    for key, value in updates.items():
        merged[key] = _merge_media_sections(before.get(key, {}), value) if (
            isinstance(value, dict) and isinstance(before.get(key, {}), dict)
        ) else value
    return merged


def prepare_product_qa_write(db: Session, sku: str, payload: dict) -> tuple[dict, bool]:
    """Plan QA replacement from locked records, never trusting client audit data.

    Omission preserves a section; explicit empty sections delete it. Same-value
    rows (including ID-free UI roundtrips) retain identity and all audit metadata.
    Changed/new rows have only writable fields and start in server-default review.
    The returned records are transaction-local, not a client-supplied snapshot.
    """
    product = db.query(Product).filter(Product.sku == sku).with_for_update().first()
    result, changed = {}, False
    for section, model, fields in (
        ("qa_items", ProductQa, ("question", "answer", "tags", "priority")),
        ("qa_negative", ProductQaNegative, ("high_freq_negative_words", "response_tone", "priority")),
    ):
        old = [_record(row) for row in db.query(model).filter(
            model.product_id == product.id,
        ).populate_existing().with_for_update().all()] if product else []
        if section not in payload:
            result[section] = old if section == "qa_items" else (old[0] if old else None)
            continue
        submitted = payload[section]
        if section == "qa_items":
            if not isinstance(submitted, list):
                raise HTTPException(status_code=400, detail="qa_items must be a list")
        else:
            if submitted is not None and not isinstance(submitted, dict):
                raise HTTPException(status_code=400, detail="qa_negative must be an object or null")
            submitted = [submitted] if submitted else []

        def contents(item):
            values = {key: item.get(key) for key in fields}
            if section == "qa_items":
                values["question"] = values["question"] or ""
                values["answer"] = values["answer"] or ""
                values["tags"] = _json(values["tags"]) or None
            return values

        remaining, records = list(old), []
        for item in submitted:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail=f"Invalid {section} item")
            values = contents(item)
            previous = next((row for row in remaining if (
                str(row["id"]) == str(item["id"]) if item.get("id") else contents(row) == values
            )), None)
            if item.get("id") and previous is None:
                raise HTTPException(status_code=404, detail="QA not found for product SKU")
            if item.get("product_id") and (not product or str(item["product_id"]) != str(product.id)):
                raise HTTPException(status_code=400, detail="QA product binding must match SKU")
            # A UI can echo the old audit verdict while editing text. It cannot
            # forge a new verdict; echoed verdicts never survive changed content.
            for key in ("integrity_status", "integrity_reason", "integrity_model", "integrity_audited_at"):
                if key not in item:
                    continue
                default = "review" if key == "integrity_status" else None
                allowed = previous.get(key) if previous else default
                value = item[key]
                if hasattr(allowed, "isoformat"):
                    allowed = allowed.isoformat()
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                if value != allowed and value != default:
                    raise HTTPException(status_code=403, detail="QA integrity fields are server-managed")
            nonempty = any(values.get(key) for key in fields[:2])
            if previous and contents(previous) == values:
                remaining.remove(previous)
                records.append(previous)
            elif nonempty:
                changed = True
                if previous:
                    remaining.remove(previous)
                if section == "qa_items" and values["tags"] is not None:
                    values["tags"] = json.dumps(values["tags"], ensure_ascii=False) if not isinstance(
                        values["tags"], str,
                    ) else values["tags"]
                records.append(values)
        changed = changed or bool(remaining)
        result[section] = records if section == "qa_items" else (records[0] if records else None)
    return result, changed


def apply_product_qa_write(db: Session, product: Product, records: dict) -> None:
    """Persist a server-prepared plan without deleting unchanged draft QA rows."""
    for section, model in (("qa_items", ProductQa), ("qa_negative", ProductQaNegative)):
        items = records[section] if section == "qa_items" else ([records[section]] if records[section] else [])
        current = {row.id: row for row in db.query(model).filter(model.product_id == product.id).all()}
        retained = {item["id"] for item in items if item.get("id")}
        for row_id, row in current.items():
            if row_id not in retained:
                db.delete(row)
        for item in items:
            if item.get("id") not in current:
                db.add(model(**{**item, "product_id": product.id}))


def authorize_product_draft_publish(db: Session, user: User, sku: str, payload: dict) -> dict:
    """Merge omitted draft media sections, then authorize the effective write."""
    payload = dict(payload)
    if "assets" in payload and not isinstance(payload["assets"], list):
        raise HTTPException(status_code=400, detail="Draft assets must be a list")
    if "media_data" in payload and not isinstance(payload["media_data"], dict):
        raise HTTPException(status_code=400, detail="Draft media_data must be an object")
    if "media" in payload and not isinstance(payload["media"], (dict, list)):
        raise HTTPException(status_code=400, detail="Draft media must be an object or list")
    product = db.query(Product).filter(Product.sku == sku).with_for_update().first()
    if product and "assets" not in payload:
        rows = db.query(ProductAsset).filter(ProductAsset.sku == sku).populate_existing().with_for_update().all()
        media_data = payload.get("media_data", payload.get("media"))
        if isinstance(media_data, dict):
            payload["media_data"] = _merge_media_sections(asset_sync.media_data_from_assets(rows), media_data)
        else:
            payload["assets"] = [_record(row) for row in rows]
    return authorize_product_replacement(db, user, sku, payload)


def authorize_product_replacement(db: Session, user: User, sku: str, payload: dict) -> dict:
    """Validate a full replacement (or new product) and return its safe payload.

    Checks persisted assets, not a potentially stale product-detail cache. Assets
    omitted from a replacement follow replace_product's manual-asset preservation
    rule. Supplied assets take precedence over media_data / dict-valued media.
    """
    payload = {**payload}
    if str(payload.get("sku") or sku).strip() != sku:
        raise HTTPException(status_code=400, detail="Request SKU must match product SKU")
    product = db.query(Product).filter(Product.sku == sku).populate_existing().with_for_update().first()
    _require(db, user, "product.edit" if product else "product.create")
    qa_records, qa_changed = prepare_product_qa_write(db, sku, payload)
    if qa_changed and not any(has_permission(db, user.id, key) for key in ("product.qa.manage", "product.edit")):
        raise HTTPException(status_code=403, detail="Permission required: product.qa.manage or product.edit")
    payload.update(qa_records)
    validate_legacy_media_replacement(db, sku, payload)
    old_rows = db.query(ProductAsset).filter(ProductAsset.sku == sku).populate_existing().with_for_update().all() if inspect(
        db.get_bind()
    ).has_table(ProductAsset.__tablename__) else []
    old = [_record(row) for row in old_rows]
    assets = payload.get("assets")
    generated = not isinstance(assets, list)
    if generated:
        media_data = payload.get("media_data") or payload.get("media")
        collector = _AssetPreview()
        asset_sync.sync_product_assets_from_media_data(
            collector, Product(sku=sku, brand=payload.get("brand")), media_data,
        )
        available = defaultdict(list)
        for item in old:
            if item.get("source_key"):
                available[_source_identity(item)].append(item)
        assets = []
        for row in collector.rows:
            item = _record(row)
            matches = available[_source_identity(item)]
            previous = matches.pop(0) if matches else None
            # Ordinary source URL lists do not carry notes; channel lists do carry labels.
            if previous:
                item = {
                    **previous,
                    **({"notes": item["notes"]} if str(item["source_key"]).startswith("channel:") else {}),
                }
            assets.append(item)
        assets.extend(item for item in old if not item.get("source_key"))
    else:
        assets = [dict(item) for item in assets if isinstance(item, dict)]

    old_by_id = {item["id"]: item for item in old}
    remaining = list(old)
    effective_assets = []
    defaults = _effective(ProductAsset, {})
    for item in assets:
        if item.get("sku") not in (None, "", sku):
            raise HTTPException(status_code=400, detail="Asset SKU must match product SKU")
        asset_id = item.get("id")
        if asset_id and asset_id not in old_by_id and not generated:
            raise HTTPException(status_code=404, detail="Asset not found for product SKU")
        if not all(str(item.get(key) or "").strip() for key in ("category_code", "category_name", "url")):
            continue  # the snapshot writer skips these records as well
        for key in ("category_code", "category_name", "url"):
            item[key] = str(item[key]).strip()
        after = _effective(ProductAsset, item)
        previous = old_by_id.get(asset_id)
        if previous not in remaining:
            previous = None
        if previous is None and not asset_id:
            previous = next((row for row in remaining if _effective(ProductAsset, row) == after), None)
        before = _effective(ProductAsset, previous) if previous else defaults
        creation_defaults = defaults
        if previous is None and after.get("status_tag") == "待审核":
            creation_defaults = {**defaults, "status_tag": "待审核"}
            before = creation_defaults
        if previous:
            remaining.remove(previous)
        if before != after or previous is None:
            _require(db, user, "media.upload")
            # source_keys is generated bookkeeping, not a user-authored tag.
            comparison = dict(after)
            if generated and previous is None:
                comparison["tags"] = {}
            _check_fields(db, user, before, comparison, creation_defaults)
        effective_assets.append(item)
    if remaining:
        _require(db, user, "media.upload")

    payload["assets"] = effective_assets
    return payload
