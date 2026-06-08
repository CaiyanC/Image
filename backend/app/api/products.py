import uuid
import os
from typing import List

from fastapi import APIRouter, Depends, Query, Request, UploadFile, File
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..core.security import require_permission, require_product_permission
from ..models.user import User
from ..schemas.product import (
    ProductCreate, ProductUpdate,
    ProductAdvancedSearchRequest,
    ProductQaCreate, ProductQaNegativeCreate,
    QaBatchImportRequest,
    ProductPromptsCreate,
)
from ..services import operation_log_service, product_service, product_vector_index_service

router = APIRouter(prefix="/api/products", tags=["products"])

# ?? Vector sync endpoints ??

@router.post("/sync-to-vector")
def sync_all_to_vector(
    current_user = Depends(require_permission("ai.call")),
    db: Session = Depends(get_db),
):
    """Sync all products to the vector knowledge base."""
    result = product_vector_index_service.index_all_products(db)
    import asyncio
    embed_result = asyncio.run(product_vector_index_service.embed_pending_chunks(db))
    return {"indexed": result, "embedding": embed_result}


@router.post("/sync-pending-to-vector")
def sync_pending_to_vector(
    limit: int = Query(50, ge=1, le=500),
    current_user = Depends(require_permission("ai.call")),
    db: Session = Depends(get_db),
):
    """Retry vector sync only for products marked as not synced."""
    return product_service.sync_pending_products_to_vector_db(db, limit=limit)


@router.post("/{sku}/sync-to-vector")
def sync_one_to_vector(
    sku: str,
    current_user = Depends(require_permission("ai.call")),
    db: Session = Depends(get_db),
):
    """Sync a single product to the vector knowledge base."""
    return product_service.sync_product_to_vector_db(db, sku)


@router.get("/vector-status")
def vector_status(
    current_user = Depends(require_permission("ai.call")),
    db: Session = Depends(get_db),
):
    """Get vector database status."""
    from ..models.knowledge_base import KnowledgeChunk
    from sqlalchemy import distinct
    total = db.query(KnowledgeChunk).count()
    synced = db.query(KnowledgeChunk).filter(KnowledgeChunk.embedding_status == "synced").count()
    failed = db.query(KnowledgeChunk).filter(KnowledgeChunk.embedding_status == "failed").count()
    skus = [row[0] for row in db.query(distinct(KnowledgeChunk.sku)).all()]
    return {
        "total_chunks": total,
        "synced": synced,
        "failed": failed,
        "products": len(skus),
        "skus": skus,
    }



@router.get("")
def get_products(
    skip: int = 0,
    limit: int = 20,
    q: str = Query(None),
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    items, total = product_service.get_products(db, skip, limit, q)
    return {"items": items, "total": total}


@router.get("/search")
def search_products(
    q: str = Query(..., description="Search keyword"),
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    items, total = product_service.get_products(db, skip, limit, q)
    return {"items": items, "total": total}


@router.post("/advanced-search")
def advanced_search_products(
    body: ProductAdvancedSearchRequest,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    items, total = product_service.advanced_search_products(db, body.model_dump())
    return {"items": items, "total": total}


@router.get("/by-sku/{sku}")
def get_product_by_sku(
    sku: str,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    return product_service.get_product_detail(db, sku)


@router.get("/{sku}")
def get_product(
    sku: str,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    return product_service.get_product_detail(db, sku)


@router.post("")
def create_product(
    product_data: ProductCreate,
    request: Request,
    current_user: User = Depends(require_product_permission("create")),
    db: Session = Depends(get_db),
):
    product = product_service.create_product(
        db, product_data.model_dump(), creator_id=current_user.id
    )
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="创建产品",
        target_type="product",
        target_id=product.id,
        target_name=product.sku,
        request_data=product_data.model_dump(),
        response_data={"sku": product.sku, "product_id": product.id},
        request=request,
    )
    product_service.sync_product_to_vector_db(db, product.sku)
    return product_service.get_product_detail(db, product.sku)


@router.put("/{sku}")
def update_product(
    sku: str,
    product_update: ProductUpdate,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    payload = product_update.model_dump(exclude_unset=True)
    product = product_service.update_product(db, sku, payload)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="编辑产品",
        target_type="product",
        target_id=product.id,
        target_name=product.sku,
        request_data=payload,
        response_data={"sku": product.sku, "product_id": product.id},
        request=request,
    )
    product_service.sync_product_to_vector_db(db, product.sku)
    return product_service.get_product_detail(db, product.sku)


@router.put("/{sku}/full")
def update_product_full(
    sku: str,
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    product_service.delete_product(db, sku)
    product = product_service.create_product(
        db, body, creator_id=current_user.id
    )
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="replace",
        action_name="覆盖更新产品",
        target_type="product",
        target_id=product.id,
        target_name=product.sku,
        request_data=body,
        response_data={"sku": product.sku, "product_id": product.id},
        request=request,
    )
    product_service.sync_product_to_vector_db(db, product.sku)
    return product_service.get_product_detail(db, product.sku)


@router.delete("/{sku}")
def delete_product(
    sku: str,
    request: Request,
    current_user: User = Depends(require_product_permission("delete")),
    db: Session = Depends(get_db),
):
    product = product_service.get_product_by_sku(db, sku)
    product_id = product.id if product else sku
    product_service.delete_product(db, sku)
    # Remove from vector DB
    product_service.delete_product_from_vector_db(db, sku)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="删除产品",
        target_type="product",
        target_id=product_id,
        target_name=sku,
        response_data={"detail": "Product deleted"},
        request=request,
    )
    return {"detail": "Product deleted"}


@router.put("/{sku}/specs")
def update_product_specs(
    sku: str,
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    result = product_service.update_product_specs(db, sku, body)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="编辑产品规格",
        target_type="product",
        target_id=result["id"],
        target_name=sku,
        request_data=body,
        request=request,
    )
    # Auto-sync affected products to vector DB
    for item in result.get("results", []):
        if item.get("status") == "success":
            product_service.sync_product_to_vector_db(db, item["sku"])
    return result


@router.put("/{sku}/business")
def update_product_business(
    sku: str,
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    result = product_service.update_product_business(db, sku, body)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="编辑产品商业信息",
        target_type="product",
        target_id=result["id"],
        target_name=sku,
        request_data=body,
        request=request,
    )
    # Auto-sync affected products to vector DB
    for item in result.get("results", []):
        if item.get("status") == "success":
            product_service.sync_product_to_vector_db(db, item["sku"])
    return result


@router.put("/{sku}/content")
def update_product_content(
    sku: str,
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    result = product_service.update_product_content(db, sku, body)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="编辑产品内容",
        target_type="product",
        target_id=result["id"],
        target_name=sku,
        request_data=body,
        request=request,
    )
    # Auto-sync affected products to vector DB
    for item in result.get("results", []):
        if item.get("status") == "success":
            product_service.sync_product_to_vector_db(db, item["sku"])
    return result


# ── QA endpoints ──

@router.get("/{sku}/qa")
def list_qa(
    sku: str,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    return [product_service.model_to_dict(item) for item in product_service.get_qa_items(db, sku)]


@router.post("/qa/batch-import")
def import_qa_batch(
    body: QaBatchImportRequest,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    items = [item.model_dump() for item in body.items]
    result = product_service.import_qa_batch(db, items, mode=body.mode)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="import",
        action_name="批量导入产品QA",
        target_type="product_qa",
        target_id="batch",
        target_name=f"{len(items)} file(s)",
        request_data={
            "mode": body.mode,
            "skus": [item.get("sku") for item in items],
            "files": [item.get("file_name") for item in items],
        },
        response_data=result,
        request=request,
    )
    # Auto-sync affected products to vector DB
    for item in result.get("results", []):
        if item.get("status") == "success":
            product_service.sync_product_to_vector_db(db, item["sku"])
    return result


@router.post("/{sku}/qa")
def add_qa(
    sku: str,
    body: ProductQaCreate,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    qa = product_service.add_qa_item(db, sku, body.model_dump())
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="新增产品QA",
        target_type="product_qa",
        target_id=qa.id,
        target_name=sku,
        request_data=body.model_dump(),
        request=request,
    )
    product_service.sync_product_to_vector_db(db, sku)
    return product_service.model_to_dict(qa)


@router.put("/{sku}/qa/{qa_id}")
def update_qa(
    sku: str,
    qa_id: str,
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    qa = product_service.update_qa_item(db, qa_id, body)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="编辑产品QA",
        target_type="product_qa",
        target_id=qa.id,
        target_name=sku,
        request_data=body,
        request=request,
    )
    product_service.sync_product_to_vector_db(db, sku)
    return product_service.model_to_dict(qa)


@router.delete("/{sku}/qa/{qa_id}")
def delete_qa(
    sku: str,
    qa_id: str,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    product_service.delete_qa_item(db, qa_id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="删除产品QA",
        target_type="product_qa",
        target_id=qa_id,
        target_name=sku,
        request=request,
    )
    product_service.sync_product_to_vector_db(db, sku)
    return {"ok": True}


@router.get("/{sku}/qa-negative")
def get_qa_negative(
    sku: str,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    return product_service.model_to_dict(product_service.get_qa_negative(db, sku))


@router.put("/{sku}/qa-negative")
def upsert_qa_negative(
    sku: str,
    body: ProductQaNegativeCreate,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    qa_negative = product_service.upsert_qa_negative(db, sku, body.model_dump())
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="upsert",
        action_name="维护产品QA负面词",
        target_type="product_qa_negative",
        target_id=qa_negative.id,
        target_name=sku,
        request_data=body.model_dump(),
        request=request,
    )
    product_service.sync_product_to_vector_db(db, sku)
    return product_service.model_to_dict(qa_negative)


# ── Prompts ──

@router.post("/{sku}/prompts")
def add_product_prompt(
    sku: str,
    body: ProductPromptsCreate,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    prompt = product_service.add_product_prompt(db, sku, body.model_dump())
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="新增产品提示词",
        target_type="product_prompt",
        target_id=prompt.id,
        target_name=sku,
        request_data=body.model_dump(),
        request=request,
    )
    return product_service.model_to_dict(prompt)


@router.delete("/{sku}/prompts/{prompt_id}")
def delete_product_prompt(
    sku: str,
    prompt_id: str,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    product_service.delete_product_prompt(db, prompt_id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="删除产品提示词",
        target_type="product_prompt",
        target_id=prompt_id,
        target_name=sku,
        request=request,
    )
    return {"ok": True}


# ── Media ──

@router.post("/{sku}/media")
def add_product_media(
    sku: str,
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    media = product_service.add_product_media(db, sku, body)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="新增产品素材",
        target_type="product_media",
        target_id=media.id,
        target_name=sku,
        request_data=body,
        request=request,
    )
    return product_service.model_to_dict(media)


@router.put("/{sku}/media/{media_id}")
def update_product_media(
    sku: str,
    media_id: str,
    body: dict,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    media = product_service.update_product_media(db, media_id, body)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="编辑产品素材",
        target_type="product_media",
        target_id=media.id,
        target_name=sku,
        request_data=body,
        request=request,
    )
    return product_service.model_to_dict(media)


@router.delete("/{sku}/media/{media_id}")
def delete_product_media(
    sku: str,
    media_id: str,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    product_service.delete_product_media(db, media_id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="删除产品素材",
        target_type="product_media",
        target_id=media_id,
        target_name=sku,
        request=request,
    )
    return {"ok": True}


# ── M2M associations ──

@router.get("/{sku}/channels")
def get_product_channels(
    sku: str,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    detail = product_service.get_product_detail(db, sku)
    return detail.get("channels", [])


@router.post("/{sku}/channels/{channel_id}")
def add_channel(
    sku: str,
    channel_id: str,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    channel = product_service.add_product_channel(db, sku, channel_id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="关联产品渠道",
        target_type="product_channel",
        target_id=channel_id,
        target_name=sku,
        request_data={"channel_id": channel_id},
        request=request,
    )
    return product_service.model_to_dict(channel)


@router.delete("/{sku}/channels/{channel_id}")
def remove_channel(
    sku: str,
    channel_id: str,
    request: Request,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    product_service.remove_product_channel(db, sku, channel_id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="移除产品渠道",
        target_type="product_channel",
        target_id=channel_id,
        target_name=sku,
        request_data={"channel_id": channel_id},
        request=request,
    )
    return {"ok": True}


# ── File uploads ──

@router.post("/images/upload")
def upload_product_images(
    files: List[UploadFile] = File(...),
    request: Request = None,
    current_user: User = Depends(require_permission("media.upload")),
    db: Session = Depends(get_db),
):
    os.makedirs(settings.IMAGE_UPLOAD_DIR, exist_ok=True)
    urls: List[str] = []
    for file in files:
        ext = os.path.splitext(file.filename or "image.png")[1] or ".png"
        name = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(settings.IMAGE_UPLOAD_DIR, name)
        with open(path, "wb") as f:
            f.write(file.file.read())
        urls.append(f"/uploads/images/{name}")
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="upload",
        action_name="上传产品图片",
        target_type="product_media_file",
        target_id="image_upload",
        target_name=f"{len(urls)} image(s)",
        response_data={"urls": urls},
        request=request,
    )
    return {"urls": urls}


@router.post("/videos/upload")
def upload_product_videos(
    files: List[UploadFile] = File(...),
    request: Request = None,
    current_user: User = Depends(require_permission("media.upload")),
    db: Session = Depends(get_db),
):
    os.makedirs(settings.VIDEO_UPLOAD_DIR, exist_ok=True)
    urls: List[str] = []
    for file in files:
        ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
        name = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(settings.VIDEO_UPLOAD_DIR, name)
        with open(path, "wb") as f:
            f.write(file.file.read())
        urls.append(f"/uploads/videos/{name}")
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="upload",
        action_name="上传产品视频",
        target_type="product_media_file",
        target_id="video_upload",
        target_name=f"{len(urls)} video(s)",
        response_data={"urls": urls},
        request=request,
    )
    return {"urls": urls}
