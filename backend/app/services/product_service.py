import json
from . import product_vector_index_service
import uuid
from datetime import date
import re
from typing import Optional, List

from fastapi import HTTPException, status
from sqlalchemy import String, asc, cast, desc
from sqlalchemy.orm import Session
from sqlalchemy.inspection import inspect

from ..models.product import Product
from ..models.product_specs import ProductSpecs
from ..models.product_business import ProductBusiness
from ..models.product_content import ProductContent
from ..models.product_media import ProductMedia
from ..models.product_prompts import ProductPrompts
from ..models.product_qa import ProductQa, ProductQaNegative
from ..models.product_associations import (
    ListingChannel, ProductListingChannel,
    SalesRegion, ProductSalesRegion,
    Certification, ProductCertification,
    Keyword, ProductKeyword,
)



def sync_product_to_vector_db(db: Session, sku: str) -> dict:
    """Sync a single product to the vector knowledge base."""
    try:
        # Clear old chunks for this product
        from ..models.knowledge_base import KnowledgeChunk, KnowledgeDocument
        old_chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.sku == sku).all()
        old_doc_ids = {c.document_id for c in old_chunks}
        for chunk in old_chunks:
            db.delete(chunk)
        for doc_id in old_doc_ids:
            doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
            if doc:
                db.delete(doc)
        db.flush()

        # Rebuild chunks from current product data
        result = product_vector_index_service.index_product(db, sku)
        db.commit()

        # Try embedding (non-blocking; fails gracefully if API key expired)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, product_vector_index_service.embed_pending_chunks(db))
                    future.result(timeout=30)
            else:
                asyncio.run(product_vector_index_service.embed_pending_chunks(db))
        except Exception:
            pass  # Embedding failure is OK, keyword search still works

        return {"sku": sku, "documents": result["documents"], "chunks": result["chunks"]}
    except Exception as e:
        return {"sku": sku, "error": str(e)}


def delete_product_from_vector_db(db: Session, sku: str) -> dict:
    """Remove a product from the vector knowledge base."""
    from ..models.knowledge_base import KnowledgeChunk, KnowledgeDocument
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.sku == sku).all()
    doc_ids = {c.document_id for c in chunks}
    for chunk in chunks:
        db.delete(chunk)
    for doc_id in doc_ids:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        if doc:
            db.delete(doc)
    db.commit()
    return {"sku": sku, "deleted_chunks": len(chunks)}


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


def _serialize_json(value):
    """Deserialize JSON string to Python object."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _to_json_str(value):
    """Serialize Python object to JSON string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


_SIZE_UNIT_ALIASES = {
    "mm": "mm",
    "毫米": "mm",
    "cm": "cm",
    "厘米": "cm",
    "m": "m",
    "米": "m",
    "in": "in",
    "inch": "in",
    "英寸": "in",
}

_SIZE_UNIT_PATTERN = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>毫米|厘米|英寸|inch|mm|cm|in|m|米)",
    re.IGNORECASE,
)


def _normalize_size_unit(unit: str) -> str:
    return _SIZE_UNIT_ALIASES.get(unit.strip().lower(), unit.strip())


def _strip_size_unit(value: str, unit: str) -> str:
    variants = [alias for alias, normalized in _SIZE_UNIT_ALIASES.items() if normalized == unit]
    variants.sort(key=len, reverse=True)
    unit_pattern = "|".join(re.escape(variant) for variant in variants)
    return re.sub(
        rf"(?P<number>\d+(?:\.\d+)?)\s*(?:{unit_pattern})",
        r"\g<number>",
        value,
        flags=re.IGNORECASE,
    ).strip()


def _normalize_size_info(value):
    parsed = _serialize_json(value)
    if not isinstance(parsed, list):
        return value

    normalized_items = []
    for item in parsed:
        if not isinstance(item, dict):
            normalized_items.append(item)
            continue

        normalized_item = dict(item)
        raw_value = str(normalized_item.get("value") or "").strip()
        existing_unit = str(normalized_item.get("unit") or "").strip()
        if not raw_value or existing_unit:
            normalized_items.append(normalized_item)
            continue

        units = {
            _normalize_size_unit(match.group("unit"))
            for match in _SIZE_UNIT_PATTERN.finditer(raw_value)
        }
        if len(units) == 1:
            unit = next(iter(units))
            normalized_item["unit"] = unit
            normalized_item["value"] = _strip_size_unit(raw_value, unit)
        else:
            normalized_item.setdefault("unit", "")

        normalized_items.append(normalized_item)

    return normalized_items


def model_to_dict(obj) -> dict | None:
    if obj is None:
        return None
    return {
        attr.key: getattr(obj, attr.key)
        for attr in inspect(obj).mapper.column_attrs
    }


def _build_detail(product: Product, db: Session) -> dict:
    pid = product.id

    specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == pid).first()
    business = db.query(ProductBusiness).filter(ProductBusiness.product_id == pid).first()
    content = db.query(ProductContent).filter(ProductContent.product_id == pid).first()
    media_list = db.query(ProductMedia).filter(ProductMedia.product_id == pid).all()
    prompts = db.query(ProductPrompts).filter(ProductPrompts.product_id == pid).all()
    qa_items = db.query(ProductQa).filter(ProductQa.product_id == pid).all()
    qa_negative = db.query(ProductQaNegative).filter(ProductQaNegative.product_id == pid).first()

    # M2M associations
    channels = (
        db.query(ListingChannel)
        .join(ProductListingChannel, ProductListingChannel.channel_id == ListingChannel.id)
        .filter(ProductListingChannel.product_id == pid)
        .all()
    )
    regions = (
        db.query(SalesRegion)
        .join(ProductSalesRegion, ProductSalesRegion.region_id == SalesRegion.id)
        .filter(ProductSalesRegion.product_id == pid)
        .all()
    )
    certifications = (
        db.query(Certification)
        .join(ProductCertification, ProductCertification.certification_id == Certification.id)
        .filter(ProductCertification.product_id == pid)
        .all()
    )
    keywords = (
        db.query(Keyword)
        .join(ProductKeyword, ProductKeyword.keyword_id == Keyword.id)
        .filter(ProductKeyword.product_id == pid)
        .all()
    )

    return {
        "id": product.id,
        "sku": product.sku,
        "barcode": product.barcode,
        "product_name_cn": product.product_name_cn,
        "product_name_en": product.product_name_en,
        "brand": product.brand,
        "series": product.series,
        "category": product.category,
        "sub_category": product.sub_category,
        "product_level": product.product_level,
        "launch_date": str(product.launch_date) if product.launch_date else None,
        "lifecycle_status": product.lifecycle_status,
        "person_in_charge": product.person_in_charge,
        "active_flag": product.active_flag,
        "sync_flag": product.sync_flag,
        "quality_note": product.quality_note,
        "status_note": product.status_note,
        "created_at": str(product.created_at) if product.created_at else None,
        "updated_at": str(product.updated_at) if product.updated_at else None,
        "specs": {
            "id": specs.id,
            "size_info": _normalize_size_info(specs.size_info),
            "capacity": _serialize_json(specs.capacity),
            "gross_weight_g": specs.gross_weight_g,
            "body_material": specs.body_material,
            "color": specs.color,
            "surface_finish": specs.surface_finish,
            "heat_source": specs.heat_source,
            "power": specs.power,
            "technical_advantages": _serialize_json(specs.technical_advantages),
            "usage_instruction": specs.usage_instruction,
            "created_at": str(specs.created_at), "updated_at": str(specs.updated_at),
        } if specs else None,
        "business": {
            "id": business.id,
            "top_selling_points": _serialize_json(business.top_selling_points),
            "target_audience": business.target_audience,
            "positioning": business.positioning,
            "price_positioning": business.price_positioning,
            "emotional_value": business.emotional_value,
            "usage_scenarios": _serialize_json(business.usage_scenarios),
            "competitor_benchmark": _serialize_json(business.competitor_benchmark),
            "created_at": str(business.created_at), "updated_at": str(business.updated_at),
        } if business else None,
        "content": {
            "id": content.id,
            "title_en": content.title_en,
            "title_cn": content.title_cn,
            "long_description_en": content.long_description_en,
            "long_description_cn": content.long_description_cn,
            "long_description_ja": content.long_description_ja,
            "search_keywords": _serialize_json(content.search_keywords),
            "amazon_title": content.amazon_title,
            "website_title": content.website_title,
            "bullet_points": _serialize_json(content.bullet_points),
            "a_plus_content": content.a_plus_content,
            "listing_cn": content.listing_cn,
            "listing_en": content.listing_en,
            "listing_ja": content.listing_ja,
            "created_at": str(content.created_at), "updated_at": str(content.updated_at),
        } if content else None,
        "media": [{
            "id": m.id,
            "sku": m.sku,
            "media_layer": m.media_layer,
            "media_group": m.media_group,
            "media_type": m.media_type,
            "channel_name": m.channel_name,
            "page_type": m.page_type,
            "media_version": m.media_version,
            "file_name": m.file_name,
            "file_path": m.file_path,
            "file_url": m.file_url,
            "file_format": m.file_format,
            "media_level": m.media_level,
            "is_real_product": m.is_real_product,
            "is_ai_generated": m.is_ai_generated,
            "is_competitor": m.is_competitor,
            "is_public": m.is_public,
            "ai_customer_usable": m.ai_customer_usable,
            "ai_marketing_usable": m.ai_marketing_usable,
            "ai_reference_usable": m.ai_reference_usable,
            "editable_flag": m.editable_flag,
            "review_status": m.review_status,
            "authorization_status": m.authorization_status,
            "forbidden_usage": m.forbidden_usage,
            "language": m.language,
            "tag_list": _serialize_json(m.tag_list),
            "created_at": str(m.created_at), "updated_at": str(m.updated_at),
        } for m in media_list],
        "prompts": [{
            "id": p.id,
            "prompt_name": p.prompt_name,
            "prompt_type": p.prompt_type,
            "prompt_text": p.prompt_text,
            "version": p.version,
        } for p in prompts],
        "qa_items": [{
            "id": q.id,
            "question": q.question,
            "answer": q.answer,
            "tags": _serialize_json(q.tags),
            "priority": q.priority,
        } for q in qa_items],
        "qa_negative": {
            "id": qa_negative.id,
            "high_freq_negative_words": qa_negative.high_freq_negative_words,
            "response_tone": qa_negative.response_tone,
            "priority": qa_negative.priority,
        } if qa_negative else None,
        "channels": [{"id": ch.id, "channel_name": ch.channel_name, "channel_code": ch.channel_code} for ch in channels],
        "regions": [{"id": r.id, "region_name": r.region_name, "region_code": r.region_code} for r in regions],
        "certifications": [{"id": c.id, "certification_name": c.certification_name, "certification_code": c.certification_code} for c in certifications],
        "keywords": [{"id": k.id, "keyword": k.keyword, "keyword_level": k.keyword_level} for k in keywords],
    }


# ── CRUD ──

def get_products(db: Session, skip: int = 0, limit: int = 20, q: str = None):
    query = db.query(Product)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Product.sku.ilike(like)) |
            (Product.product_name_cn.ilike(like)) |
            (Product.product_name_en.ilike(like)) |
            (Product.brand.ilike(like))
        )
    total = query.count()
    products = query.order_by(Product.created_at.desc()).offset(skip).limit(limit).all()
    items = []
    for p in products:
        items.append({
            "id": p.id,
            "sku": p.sku,
            "product_name_cn": p.product_name_cn,
            "product_name_en": p.product_name_en,
            "brand": p.brand,
            "series": p.series,
            "category": p.category,
            "product_level": p.product_level,
            "active_flag": p.active_flag,
            "created_at": str(p.created_at) if p.created_at else None,
        })
    return items, total


def advanced_search_products(db: Session, filters: dict):
    query = (
        db.query(Product)
        .outerjoin(ProductSpecs, ProductSpecs.product_id == Product.id)
        .outerjoin(ProductBusiness, ProductBusiness.product_id == Product.id)
        .outerjoin(ProductContent, ProductContent.product_id == Product.id)
    )

    def ilike(column, value):
        if value is None or str(value).strip() == "":
            return
        query_filters.append(column.ilike(f"%{str(value).strip()}%"))

    query_filters = []
    keyword = (filters.get("keyword") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query_filters.append(
            (Product.sku.ilike(like)) |
            (Product.barcode.ilike(like)) |
            (Product.product_name_cn.ilike(like)) |
            (Product.product_name_en.ilike(like)) |
            (Product.brand.ilike(like)) |
            (Product.series.ilike(like)) |
            (Product.category.ilike(like)) |
            (Product.sub_category.ilike(like)) |
            (Product.product_level.ilike(like)) |
            (Product.lifecycle_status.ilike(like)) |
            (Product.person_in_charge.ilike(like)) |
            (Product.quality_note.ilike(like)) |
            (Product.status_note.ilike(like)) |
            (ProductSpecs.size_info.ilike(like)) |
            (ProductSpecs.capacity.ilike(like)) |
            (cast(ProductSpecs.gross_weight_g, String).ilike(like)) |
            (ProductSpecs.body_material.ilike(like)) |
            (ProductSpecs.color.ilike(like)) |
            (ProductSpecs.surface_finish.ilike(like)) |
            (ProductSpecs.heat_source.ilike(like)) |
            (ProductSpecs.power.ilike(like)) |
            (ProductSpecs.technical_advantages.ilike(like)) |
            (ProductSpecs.usage_instruction.ilike(like)) |
            (ProductBusiness.top_selling_points.ilike(like)) |
            (ProductBusiness.target_audience.ilike(like)) |
            (ProductBusiness.positioning.ilike(like)) |
            (ProductBusiness.price_positioning.ilike(like)) |
            (ProductBusiness.emotional_value.ilike(like)) |
            (ProductBusiness.usage_scenarios.ilike(like)) |
            (ProductBusiness.competitor_benchmark.ilike(like)) |
            (ProductContent.title_en.ilike(like)) |
            (ProductContent.title_cn.ilike(like)) |
            (ProductContent.long_description_en.ilike(like)) |
            (ProductContent.long_description_cn.ilike(like)) |
            (ProductContent.long_description_ja.ilike(like)) |
            (ProductContent.search_keywords.ilike(like)) |
            (ProductContent.amazon_title.ilike(like)) |
            (ProductContent.website_title.ilike(like)) |
            (ProductContent.bullet_points.ilike(like)) |
            (ProductContent.a_plus_content.ilike(like)) |
            (ProductContent.listing_cn.ilike(like)) |
            (ProductContent.listing_en.ilike(like)) |
            (ProductContent.listing_ja.ilike(like))
        )

    ilike(Product.sku, filters.get("sku"))
    ilike(Product.barcode, filters.get("barcode"))
    product_name = filters.get("product_name")
    if product_name:
        like = f"%{product_name.strip()}%"
        query_filters.append((Product.product_name_cn.ilike(like)) | (Product.product_name_en.ilike(like)))
    ilike(Product.brand, filters.get("brand"))
    ilike(Product.series, filters.get("series"))
    ilike(Product.category, filters.get("category"))
    ilike(Product.sub_category, filters.get("sub_category"))
    ilike(Product.product_level, filters.get("product_level"))
    ilike(Product.lifecycle_status, filters.get("lifecycle_status"))
    ilike(Product.person_in_charge, filters.get("person_in_charge"))
    ilike(Product.quality_note, filters.get("quality_note"))

    if filters.get("active_flag") is not None:
        query_filters.append(Product.active_flag == bool(filters["active_flag"]))

    launch_from = _parse_date(filters.get("launch_date_from"))
    launch_to = _parse_date(filters.get("launch_date_to"))
    if launch_from:
        query_filters.append(Product.launch_date >= launch_from)
    if launch_to:
        query_filters.append(Product.launch_date <= launch_to)

    ilike(ProductSpecs.capacity, filters.get("capacity"))
    ilike(ProductSpecs.body_material, filters.get("body_material"))
    ilike(ProductSpecs.color, filters.get("color"))
    ilike(ProductSpecs.surface_finish, filters.get("surface_finish"))
    ilike(ProductSpecs.heat_source, filters.get("heat_source"))
    ilike(ProductSpecs.power, filters.get("power"))
    if filters.get("gross_weight_min") is not None:
        query_filters.append(ProductSpecs.gross_weight_g >= filters["gross_weight_min"])
    if filters.get("gross_weight_max") is not None:
        query_filters.append(ProductSpecs.gross_weight_g <= filters["gross_weight_max"])

    ilike(ProductBusiness.top_selling_points, filters.get("top_selling_points"))
    ilike(ProductBusiness.target_audience, filters.get("target_audience"))
    ilike(ProductBusiness.positioning, filters.get("positioning"))
    ilike(ProductBusiness.price_positioning, filters.get("price_positioning"))
    ilike(ProductBusiness.emotional_value, filters.get("emotional_value"))
    ilike(ProductBusiness.usage_scenarios, filters.get("usage_scenarios"))
    ilike(ProductBusiness.competitor_benchmark, filters.get("competitor_benchmark"))

    for item in query_filters:
        query = query.filter(item)

    if filters.get("channel"):
        like = f"%{filters['channel'].strip()}%"
        ids = db.query(ProductListingChannel.product_id).join(
            ListingChannel, ProductListingChannel.channel_id == ListingChannel.id
        ).filter(ListingChannel.channel_name.ilike(like))
        query = query.filter(Product.id.in_(ids))

    if filters.get("region"):
        like = f"%{filters['region'].strip()}%"
        ids = db.query(ProductSalesRegion.product_id).join(
            SalesRegion, ProductSalesRegion.region_id == SalesRegion.id
        ).filter(SalesRegion.region_name.ilike(like))
        query = query.filter(Product.id.in_(ids))

    if filters.get("certification"):
        like = f"%{filters['certification'].strip()}%"
        ids = db.query(ProductCertification.product_id).join(
            Certification, ProductCertification.certification_id == Certification.id
        ).filter(Certification.certification_name.ilike(like))
        query = query.filter(Product.id.in_(ids))

    if filters.get("search_keyword"):
        like = f"%{filters['search_keyword'].strip()}%"
        ids = db.query(ProductKeyword.product_id).join(
            Keyword, ProductKeyword.keyword_id == Keyword.id
        ).filter(Keyword.keyword.ilike(like))
        query = query.filter(Product.id.in_(ids))

    query = query.distinct()
    total = query.count()

    sort_by = filters.get("sort_by") or "updated_at"
    sort_order = (filters.get("sort_order") or "desc").lower()
    sort_columns = {
        "sku": Product.sku,
        "brand": Product.brand,
        "category": Product.category,
        "launch_date": Product.launch_date,
        "updated_at": Product.updated_at,
        "created_at": Product.created_at,
        "gross_weight_g": ProductSpecs.gross_weight_g,
    }
    sort_column = sort_columns.get(sort_by, Product.updated_at)
    query = query.order_by(asc(sort_column) if sort_order == "asc" else desc(sort_column))

    skip = max(int(filters.get("skip") or 0), 0)
    limit = min(max(int(filters.get("limit") or 20), 1), 100)
    products = query.offset(skip).limit(limit).all()

    return [_build_search_item(db, product) for product in products], total


def _build_search_item(db: Session, product: Product) -> dict:
    specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
    business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).first()
    return {
        "id": product.id,
        "sku": product.sku,
        "barcode": product.barcode,
        "product_name_cn": product.product_name_cn,
        "product_name_en": product.product_name_en,
        "brand": product.brand,
        "series": product.series,
        "category": product.category,
        "sub_category": product.sub_category,
        "product_level": product.product_level,
        "launch_date": str(product.launch_date) if product.launch_date else None,
        "lifecycle_status": product.lifecycle_status,
        "person_in_charge": product.person_in_charge,
        "active_flag": product.active_flag,
        "quality_note": product.quality_note,
        "gross_weight_g": specs.gross_weight_g if specs else None,
        "capacity": _serialize_json(specs.capacity) if specs else None,
        "body_material": specs.body_material if specs else None,
        "color": specs.color if specs else None,
        "heat_source": specs.heat_source if specs else None,
        "top_selling_points": _serialize_json(business.top_selling_points) if business else None,
        "usage_scenarios": _serialize_json(business.usage_scenarios) if business else None,
        "created_at": str(product.created_at) if product.created_at else None,
        "updated_at": str(product.updated_at) if product.updated_at else None,
    }


def get_product_by_sku(db: Session, sku: str) -> Optional[Product]:
    return db.query(Product).filter(Product.sku == sku).first()


def get_product_by_id(db: Session, product_id: str) -> Optional[Product]:
    return db.query(Product).filter(Product.id == product_id).first()


def get_product_detail(db: Session, sku: str) -> dict:
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return _build_detail(product, db)


def create_product(db: Session, data: dict, creator_id: str = None) -> Product:
    sku = data.get("sku", "").strip()
    if not sku:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKU is required")
    if get_product_by_sku(db, sku):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKU already exists")

    # Validate required fields per design doc
    required_fields = {
        "barcode": "条形码",
        "product_name_cn": "中文产品名",
        "product_name_en": "英文产品名",
        "brand": "品牌",
        "person_in_charge": "负责人",
    }
    for field, label in required_fields.items():
        val = data.get(field)
        if not val or (isinstance(val, str) and not val.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label}（{field}）为必填项"
            )

    product_id = str(uuid.uuid4())

    product = Product(
        id=product_id,
        sku=sku,
        barcode=data["barcode"],
        product_name_cn=data["product_name_cn"],
        product_name_en=data["product_name_en"],
        brand=data["brand"],
        series=data.get("series"),
        category=data.get("category"),
        sub_category=data.get("sub_category"),
        product_level=data.get("product_level"),
        launch_date=_parse_date(data.get("launch_date")),
        lifecycle_status=data.get("lifecycle_status"),
        person_in_charge=data["person_in_charge"],
        active_flag=data.get("active_flag", True),
        sync_flag=data.get("sync_flag", False),
        quality_note=data.get("quality_note"),
        status_note=data.get("status_note"),
    )
    db.add(product)

    # Specs — accept both flat (specs_data) and nested (specs) formats
    specs_data = data.get("specs_data") or data.get("specs") or {}
    db.add(ProductSpecs(
        product_id=product_id,
        size_info=_to_json_str(_normalize_size_info(specs_data.get("size_info"))),
        capacity=_to_json_str(specs_data.get("capacity")),
        gross_weight_g=specs_data.get("gross_weight_g"),
        body_material=specs_data.get("body_material"),
        color=specs_data.get("color"),
        surface_finish=specs_data.get("surface_finish"),
        heat_source=specs_data.get("heat_source"),
        power=specs_data.get("power"),
        technical_advantages=_to_json_str(specs_data.get("technical_advantages")),
        usage_instruction=specs_data.get("usage_instruction"),
    ))

    # Business — accept both flat and nested formats
    biz_data = data.get("business_data") or data.get("business") or {}
    db.add(ProductBusiness(
        product_id=product_id,
        top_selling_points=_to_json_str(biz_data.get("top_selling_points")),
        target_audience=biz_data.get("target_audience"),
        positioning=biz_data.get("positioning"),
        price_positioning=biz_data.get("price_positioning"),
        emotional_value=biz_data.get("emotional_value"),
        usage_scenarios=_to_json_str(biz_data.get("usage_scenarios")),
        competitor_benchmark=_to_json_str(biz_data.get("competitor_benchmark")),
    ))

    # Content — accept both flat and nested formats
    content_data = data.get("content_data") or data.get("content") or {}
    db.add(ProductContent(
        product_id=product_id,
        title_en=content_data.get("title_en"),
        title_cn=content_data.get("title_cn"),
        long_description_en=content_data.get("long_description_en"),
        long_description_cn=content_data.get("long_description_cn"),
        long_description_ja=content_data.get("long_description_ja"),
        search_keywords=_to_json_str(content_data.get("search_keywords")),
        amazon_title=content_data.get("amazon_title"),
        website_title=content_data.get("website_title"),
        bullet_points=_to_json_str(content_data.get("bullet_points")),
        a_plus_content=content_data.get("a_plus_content"),
        listing_cn=content_data.get("listing_cn"),
        listing_en=content_data.get("listing_en"),
        listing_ja=content_data.get("listing_ja"),
    ))

    # QA items
    qa_items = data.get("qa_items") or []
    for qa in qa_items:
        if qa.get("question") or qa.get("answer"):
            db.add(ProductQa(
                product_id=product_id,
                question=qa.get("question", ""),
                answer=qa.get("answer", ""),
                tags=_to_json_str(qa.get("tags")),
                priority=qa.get("priority"),
            ))

    # QA negative
    qa_neg = data.get("qa_negative") or {}
    if qa_neg.get("high_freq_negative_words") or qa_neg.get("response_tone"):
        db.add(ProductQaNegative(
            product_id=product_id,
            high_freq_negative_words=qa_neg.get("high_freq_negative_words"),
            response_tone=qa_neg.get("response_tone"),
            priority=qa_neg.get("priority"),
        ))

    # Product prompts
    prompts_raw = data.get("prompts") or []
    if isinstance(prompts_raw, dict):
        prompts = prompts_raw.get("prompts") or []
    else:
        prompts = prompts_raw if isinstance(prompts_raw, list) else []
    for p in prompts:
        if isinstance(p, dict) and p.get("prompt_text"):
            db.add(ProductPrompts(
                product_id=product_id,
                sku=sku,
                prompt_name=p.get("prompt_name"),
                prompt_type=p.get("prompt_type"),
                prompt_text=p.get("prompt_text"),
                version=p.get("version"),
            ))

    # Sync M2M associations (channels, regions, certifications, keywords)
    sync_product_m2m(db, product_id, data)

    db.commit()
    db.refresh(product)
    return product


def update_product(db: Session, sku: str, update_data: dict) -> Product:
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    field_map = {
        "product_name_cn", "product_name_en", "brand", "series",
        "category", "sub_category", "product_level", "lifecycle_status",
        "person_in_charge", "active_flag", "sync_flag", "quality_note", "status_note", "barcode",
    }
    for key, value in update_data.items():
        if key in field_map and value is not None:
            setattr(product, key, value)
        elif key == "sku" and value and value != sku:
            if get_product_by_sku(db, value):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKU already exists")
            product.sku = value
        elif key == "launch_date" and value is not None:
            parsed = _parse_date(value)
            if parsed is not None:
                product.launch_date = parsed

    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, sku: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    pid = product.id
    for model in [
        ProductQa, ProductQaNegative, ProductPrompts, ProductMedia,
        ProductContent, ProductBusiness, ProductSpecs,
        ProductListingChannel, ProductSalesRegion,
        ProductCertification, ProductKeyword,
    ]:
        db.query(model).filter(model.product_id == pid).delete()

    db.delete(product)
    db.commit()


# ── Sub-table updaters ──

def _upsert_sub(db: Session, model_class, product_id: str, fields: dict):
    obj = db.query(model_class).filter(model_class.product_id == product_id).first()
    if obj:
        for col, val in fields.items():
            setattr(obj, col, val)
    else:
        obj = model_class(product_id=product_id, **fields)
        db.add(obj)
    return obj


def update_product_specs(db: Session, sku: str, data: dict) -> dict:
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    fields = {}
    if "size_info" in data:
        fields["size_info"] = _to_json_str(_normalize_size_info(data["size_info"]))
    for k in ["capacity", "gross_weight_g", "body_material", "color",
               "surface_finish", "heat_source", "power", "usage_instruction"]:
        if k in data and data[k] is not None:
            fields[k] = data[k]
    if "technical_advantages" in data:
        fields["technical_advantages"] = _to_json_str(data["technical_advantages"])

    _upsert_sub(db, ProductSpecs, product.id, fields)
    db.commit()
    return get_product_detail(db, sku)


def update_product_business(db: Session, sku: str, data: dict) -> dict:
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    fields = {}
    json_fields = {"top_selling_points", "usage_scenarios", "competitor_benchmark"}
    text_fields = {"target_audience", "positioning", "price_positioning", "emotional_value"}

    for k in json_fields:
        if k in data and data[k] is not None:
            fields[k] = _to_json_str(data[k])
    for k in text_fields:
        if k in data and data[k] is not None:
            fields[k] = data[k]

    _upsert_sub(db, ProductBusiness, product.id, fields)
    db.commit()
    return get_product_detail(db, sku)


def update_product_content(db: Session, sku: str, data: dict) -> dict:
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    fields = {}
    json_fields = {"search_keywords", "bullet_points"}
    text_fields = {
        "title_en", "title_cn", "long_description_en", "long_description_cn",
        "long_description_ja", "amazon_title", "website_title",
        "a_plus_content", "listing_cn", "listing_en", "listing_ja",
    }

    for k in json_fields:
        if k in data and data[k] is not None:
            fields[k] = _to_json_str(data[k])
    for k in text_fields:
        if k in data and data[k] is not None:
            fields[k] = data[k]

    _upsert_sub(db, ProductContent, product.id, fields)
    db.commit()
    return get_product_detail(db, sku)


# ── QA ──

def get_qa_items(db: Session, sku: str) -> list:
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return db.query(ProductQa).filter(ProductQa.product_id == product.id).all()


def add_qa_item(db: Session, sku: str, data: dict):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    qa = ProductQa(
        product_id=product.id,
        question=data["question"],
        answer=data["answer"],
        tags=_to_json_str(data.get("tags")),
        priority=data.get("priority"),
    )
    db.add(qa)
    db.commit()
    db.refresh(qa)
    return qa


def update_qa_item(db: Session, qa_id: str, data: dict):
    qa = db.query(ProductQa).filter(ProductQa.id == qa_id).first()
    if not qa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QA item not found")
    for k in ("question", "answer", "priority"):
        if k in data and data[k] is not None:
            setattr(qa, k, data[k])
    if "tags" in data and data["tags"] is not None:
        qa.tags = _to_json_str(data["tags"])
    db.commit()
    db.refresh(qa)
    return qa


def delete_qa_item(db: Session, qa_id: str):
    qa = db.query(ProductQa).filter(ProductQa.id == qa_id).first()
    if not qa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QA item not found")
    db.delete(qa)
    db.commit()


def import_qa_batch(db: Session, items: list[dict], mode: str = "replace") -> dict:
    results = []
    total_qa_created = 0
    total_negative_updated = 0

    for item in items:
        sku = (item.get("sku") or "").strip()
        item_mode = item.get("mode") or mode or "replace"
        qa_items = item.get("qa_items") or []
        review_items = item.get("review_items") or []
        result = {
            "sku": sku,
            "file_name": item.get("file_name"),
            "status": "success",
            "qa_created": 0,
            "negative_updated": False,
            "message": "",
        }

        product = get_product_by_sku(db, sku)
        if not product:
            result["status"] = "skipped"
            result["message"] = "产品不存在"
            results.append(result)
            continue

        if item_mode not in {"replace", "append"}:
            result["status"] = "error"
            result["message"] = "导入模式无效"
            results.append(result)
            continue

        if item_mode == "replace":
            db.query(ProductQa).filter(ProductQa.product_id == product.id).delete(synchronize_session=False)
            db.query(ProductQaNegative).filter(ProductQaNegative.product_id == product.id).delete(synchronize_session=False)

        for index, qa in enumerate(qa_items, start=1):
            question = (qa.get("question") or qa.get("q") or "").strip()
            answer = (qa.get("answer") or qa.get("a") or "").strip()
            if not question or not answer:
                continue
            priority = qa.get("priority")
            if priority is None:
                priority = qa.get("no") or index
            db.add(ProductQa(
                product_id=product.id,
                question=question,
                answer=answer,
                tags=_to_json_str(qa.get("tags")),
                priority=priority,
            ))
            result["qa_created"] += 1

        valid_reviews = [
            r for r in review_items
            if (r.get("keyword") or "").strip() and (r.get("response") or "").strip()
        ]
        if valid_reviews:
            keywords = []
            response_lines = []
            for review in valid_reviews:
                keyword = review["keyword"].strip()
                response = review["response"].strip()
                if keyword not in keywords:
                    keywords.append(keyword)
                response_lines.append(f"【{keyword}】{response}")

            obj = db.query(ProductQaNegative).filter(ProductQaNegative.product_id == product.id).first()
            if obj:
                obj.high_freq_negative_words = "\n".join(keywords)
                obj.response_tone = "\n".join(response_lines)
                obj.priority = 1
            else:
                db.add(ProductQaNegative(
                    product_id=product.id,
                    high_freq_negative_words="\n".join(keywords),
                    response_tone="\n".join(response_lines),
                    priority=1,
                ))
            result["negative_updated"] = True
            total_negative_updated += 1

        total_qa_created += result["qa_created"]
        results.append(result)

    db.commit()
    return {
        "total_files": len(items),
        "total_qa_created": total_qa_created,
        "total_negative_updated": total_negative_updated,
        "results": results,
    }


def get_qa_negative(db: Session, sku: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return db.query(ProductQaNegative).filter(ProductQaNegative.product_id == product.id).first()


def upsert_qa_negative(db: Session, sku: str, data: dict):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    obj = db.query(ProductQaNegative).filter(ProductQaNegative.product_id == product.id).first()
    if obj:
        for k in ("high_freq_negative_words", "response_tone", "priority"):
            if k in data and data[k] is not None:
                setattr(obj, k, data[k])
    else:
        obj = ProductQaNegative(
            product_id=product.id,
            high_freq_negative_words=data.get("high_freq_negative_words"),
            response_tone=data.get("response_tone"),
            priority=data.get("priority"),
        )
        db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# ── ProductPrompts ──

def add_product_prompt(db: Session, sku: str, data: dict):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    prompt = ProductPrompts(
        product_id=product.id,
        sku=sku,
        prompt_name=data.get("prompt_name"),
        prompt_type=data.get("prompt_type"),
        prompt_text=data["prompt_text"],
        version=data.get("version", "1"),
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def delete_product_prompt(db: Session, prompt_id: str):
    prompt = db.query(ProductPrompts).filter(ProductPrompts.id == prompt_id).first()
    if prompt:
        db.delete(prompt)
        db.commit()


# ── ProductMedia ──

def add_product_media(db: Session, sku: str, data: dict):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    media = ProductMedia(
        product_id=product.id,
        sku=sku,
        media_layer=data.get("media_layer", "raw"),
        media_group=data.get("media_group", ""),
        media_type=data.get("media_type"),
        channel_name=data.get("channel_name"),
        page_type=data.get("page_type"),
        media_version=data.get("media_version"),
        file_name=data.get("file_name", ""),
        file_path=data.get("file_path", ""),
        file_url=data.get("file_url"),
        file_format=data.get("file_format"),
        media_level=data.get("media_level", "C"),
        is_real_product=data.get("is_real_product", True),
        is_ai_generated=data.get("is_ai_generated", False),
        is_competitor=data.get("is_competitor", False),
        is_public=data.get("is_public", False),
        ai_customer_usable=data.get("ai_customer_usable", False),
        ai_marketing_usable=data.get("ai_marketing_usable", False),
        ai_reference_usable=data.get("ai_reference_usable", False),
        editable_flag=data.get("editable_flag", False),
        review_status=data.get("review_status", "pending"),
        authorization_status=data.get("authorization_status", "unknown"),
        forbidden_usage=data.get("forbidden_usage"),
        language=data.get("language"),
        tag_list=_to_json_str(data.get("tag_list")),
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


def update_product_media(db: Session, media_id: str, data: dict):
    media = db.query(ProductMedia).filter(ProductMedia.id == media_id).first()
    if not media:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    updatable = {
        "media_layer", "media_group", "media_type", "channel_name", "page_type",
        "media_version", "file_name", "file_path", "file_url", "file_format",
        "media_level", "is_real_product", "is_ai_generated", "is_competitor",
        "is_public", "ai_customer_usable", "ai_marketing_usable",
        "ai_reference_usable", "editable_flag", "review_status",
        "authorization_status", "forbidden_usage", "language",
    }
    for k, v in data.items():
        if k == "tag_list":
            media.tag_list = _to_json_str(v)
        elif k in updatable and v is not None:
            setattr(media, k, v)

    db.commit()
    db.refresh(media)
    return media


def delete_product_media(db: Session, media_id: str):
    media = db.query(ProductMedia).filter(ProductMedia.id == media_id).first()
    if not media:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
    db.delete(media)
    db.commit()


# ── M2M association helpers ──

def _find_or_create_channel(db: Session, name: str) -> str:
    """Find or create a listing channel, return its ID."""
    obj = db.query(ListingChannel).filter(ListingChannel.channel_name == name).first()
    if obj:
        return obj.id
    obj = ListingChannel(channel_name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _find_or_create_region(db: Session, name: str) -> str:
    obj = db.query(SalesRegion).filter(SalesRegion.region_name == name).first()
    if obj:
        return obj.id
    obj = SalesRegion(region_name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _find_or_create_certification(db: Session, name: str) -> str:
    obj = db.query(Certification).filter(Certification.certification_name == name).first()
    if obj:
        return obj.id
    obj = Certification(certification_name=name)
    db.add(obj)
    db.flush()
    return obj.id


def _find_or_create_keyword(db: Session, word: str, level: str = None) -> str:
    obj = db.query(Keyword).filter(Keyword.keyword == word).first()
    if obj:
        return obj.id
    obj = Keyword(keyword=word, keyword_level=level)
    db.add(obj)
    db.flush()
    return obj.id


def sync_product_m2m(db: Session, product_id: str, data: dict):
    """Sync M2M associations from draft/product data (channels, regions, certs, keywords)."""
    specs = data.get("specs_data") or data.get("specs") or {}
    biz = data.get("business_data") or data.get("business") or {}
    content = data.get("content_data") or data.get("content") or {}

    # Track added IDs within this batch to prevent duplicates
    added_channels = set()
    added_regions = set()
    added_certs = set()
    added_keywords = set()

    # Listing channels — stored in business.listing_channel or top-level
    has_channels = "listing_channel" in biz or "listing_channel" in data
    channels = biz.get("listing_channel") if "listing_channel" in biz else data.get("listing_channel", [])
    if has_channels:
        db.query(ProductListingChannel).filter(ProductListingChannel.product_id == product_id).delete()
    channels = channels or []
    if isinstance(channels, str):
        channels = [c.strip() for c in channels.split(",") if c.strip()]
    for name in channels:
        if not name:
            continue
        cid = _find_or_create_channel(db, name)
        if cid in added_channels:
            continue
        added_channels.add(cid)
        db.add(ProductListingChannel(product_id=product_id, channel_id=cid))

    # Sales regions — stored in specs.sales_region
    has_regions = "sales_region" in specs or "sales_region" in data
    regions = specs.get("sales_region") if "sales_region" in specs else data.get("sales_region", [])
    if has_regions:
        db.query(ProductSalesRegion).filter(ProductSalesRegion.product_id == product_id).delete()
    regions = regions or []
    if isinstance(regions, str):
        regions = [r.strip() for r in regions.split(",") if r.strip()]
    for name in regions:
        if not name:
            continue
        rid = _find_or_create_region(db, name)
        if rid in added_regions:
            continue
        added_regions.add(rid)
        db.add(ProductSalesRegion(product_id=product_id, region_id=rid))

    # Certifications — stored in specs.certifications
    has_certs = "certifications" in specs or "certifications" in data
    certs = specs.get("certifications") if "certifications" in specs else data.get("certifications", [])
    if has_certs:
        db.query(ProductCertification).filter(ProductCertification.product_id == product_id).delete()
    certs = certs or []
    if isinstance(certs, str):
        certs = [c.strip() for c in certs.split(",") if c.strip()]
    for name in certs:
        if not name:
            continue
        cid = _find_or_create_certification(db, name)
        if cid in added_certs:
            continue
        added_certs.add(cid)
        db.add(ProductCertification(product_id=product_id, certification_id=cid))

    # Keywords — stored in content.search_keywords
    has_keywords = "search_keywords" in content or "search_keywords" in data
    keywords = content.get("search_keywords") if "search_keywords" in content else data.get("search_keywords", [])
    if has_keywords:
        db.query(ProductKeyword).filter(ProductKeyword.product_id == product_id).delete()
    keywords = keywords or []
    for kw in keywords:
        word = kw.get("keyword") if isinstance(kw, dict) else str(kw)
        level = kw.get("priority") if isinstance(kw, dict) else None
        if not word:
            continue
        kid = _find_or_create_keyword(db, word, level)
        if kid in added_keywords:
            continue
        added_keywords.add(kid)
        db.add(ProductKeyword(product_id=product_id, keyword_id=kid))

    db.flush()


def get_listing_channels(db: Session) -> list:
    return db.query(ListingChannel).all()


def add_product_channel(db: Session, sku: str, channel_id: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    existing = db.query(ProductListingChannel).filter(
        ProductListingChannel.product_id == product.id,
        ProductListingChannel.channel_id == channel_id,
    ).first()
    if existing:
        return existing
    plc = ProductListingChannel(product_id=product.id, channel_id=channel_id)
    db.add(plc)
    db.commit()
    db.refresh(plc)
    return plc


def remove_product_channel(db: Session, sku: str, channel_id: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    db.query(ProductListingChannel).filter(
        ProductListingChannel.product_id == product.id,
        ProductListingChannel.channel_id == channel_id,
    ).delete()
    db.commit()


def add_product_region(db: Session, sku: str, region_id: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    existing = db.query(ProductSalesRegion).filter(
        ProductSalesRegion.product_id == product.id,
        ProductSalesRegion.region_id == region_id,
    ).first()
    if existing:
        return existing
    psr = ProductSalesRegion(product_id=product.id, region_id=region_id)
    db.add(psr)
    db.commit()
    db.refresh(psr)
    return psr


def remove_product_region(db: Session, sku: str, region_id: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    db.query(ProductSalesRegion).filter(
        ProductSalesRegion.product_id == product.id,
        ProductSalesRegion.region_id == region_id,
    ).delete()
    db.commit()


def add_product_certification(db: Session, sku: str, certification_id: str, file_path: str = None):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    existing = db.query(ProductCertification).filter(
        ProductCertification.product_id == product.id,
        ProductCertification.certification_id == certification_id,
    ).first()
    if existing:
        return existing
    pc = ProductCertification(
        product_id=product.id,
        certification_id=certification_id,
        certification_file_path=file_path,
    )
    db.add(pc)
    db.commit()
    db.refresh(pc)
    return pc


def remove_product_certification(db: Session, sku: str, certification_id: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    db.query(ProductCertification).filter(
        ProductCertification.product_id == product.id,
        ProductCertification.certification_id == certification_id,
    ).delete()
    db.commit()


def add_product_keyword(db: Session, sku: str, keyword_id: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    existing = db.query(ProductKeyword).filter(
        ProductKeyword.product_id == product.id,
        ProductKeyword.keyword_id == keyword_id,
    ).first()
    if existing:
        return existing
    pk = ProductKeyword(product_id=product.id, keyword_id=keyword_id)
    db.add(pk)
    db.commit()
    db.refresh(pk)
    return pk


def remove_product_keyword(db: Session, sku: str, keyword_id: str):
    product = get_product_by_sku(db, sku)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    db.query(ProductKeyword).filter(
        ProductKeyword.product_id == product.id,
        ProductKeyword.keyword_id == keyword_id,
    ).delete()
    db.commit()
