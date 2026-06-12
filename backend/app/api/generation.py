import base64
import binascii

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from ..core.database import get_db
from ..core.security import require_permission
from ..models.user import User
from ..schemas.generation import (
    GenerationResponse,
    Txt2ImgRequest,
    Img2ImgRequest,
    Img2ImgGeminiRequest,
    ImagePayload,
    Txt2VidRequest,
    ModelInfo,
    GenerationParams,
)
from ..services import generation_service
from ..services.dmxapi_service import get_available_models

router = APIRouter(prefix="/api/generation", tags=["generation"])
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_REFERENCE_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_REFERENCE_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MIME_TO_EXTENSION = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


@router.get("/models", response_model=List[ModelInfo])
def get_models(
    current_user: User = Depends(require_permission("ai.generate")),
    db: Session = Depends(get_db),
):
    return get_available_models(db)


@router.post("/txt2img", response_model=GenerationResponse)
async def txt2img(
    req: Txt2ImgRequest,
    current_user: User = Depends(require_permission("ai.generate")),
    db: Session = Depends(get_db),
):
    return await generation_service.create_txt2img(db, current_user, req)


@router.post("/img2img", response_model=GenerationResponse)
async def img2img(
    prompt: str = Form(...),
    model_name: str = Form("gpt-image-2-ssvip"),
    negative_prompt: str = Form(""),
    size: str = Form("1024x1024"),
    n: int = Form(1),
    quality: str = Form("medium"),
    output_format: str = Form("png"),
    output_compression: int = Form(0),
    moderation: str = Form("low"),
    background: Optional[str] = Form(None),
    images: List[UploadFile] = File(...),
    current_user: User = Depends(require_permission("ai.generate")),
    db: Session = Depends(get_db),
):
    from ..schemas.generation import Img2ImgRequest, GenerationParams

    if len(images) > 4:
        raise HTTPException(status_code=400, detail="最多支持 4 张参考图")
    if len(images) == 0:
        raise HTTPException(status_code=400, detail="请至少上传 1 张参考图")

    req = Img2ImgRequest(
        prompt=prompt,
        model_name=model_name,
        negative_prompt=negative_prompt or None,
        params=GenerationParams(
            size=size,
            n=n,
            quality=quality,
            output_format=output_format,
            output_compression=output_compression if output_compression > 0 else None,
            moderation=moderation,
            background=background,
        ),
    )
    image_data = []
    for img in images:
        image_data.append((await _read_reference_upload(img), img.filename or "image.png"))
    return await generation_service.create_img2img(db, current_user, req, image_data)


@router.post("/img2img-gemini", response_model=GenerationResponse)
async def img2img_gemini(
    req: Img2ImgGeminiRequest,
    current_user: User = Depends(require_permission("ai.generate")),
    db: Session = Depends(get_db),
):
    if len(req.images) > 4:
        raise HTTPException(status_code=400, detail="最多支持 4 张参考图")
    if len(req.images) == 0:
        raise HTTPException(status_code=400, detail="请至少上传 1 张参考图")

    dto = Img2ImgRequest(
        prompt=req.prompt,
        model_name=req.model_name,
        negative_prompt=req.negative_prompt,
        params=req.params,
    )
    image_data = []
    for idx, img in enumerate(req.images):
        img_bytes, ext = _decode_reference_payload(img)
        image_data.append((img_bytes, f"ref_{idx}.{ext}"))
    return await generation_service.create_img2img(db, current_user, dto, image_data)


@router.post("/txt2vid", response_model=GenerationResponse)
async def txt2vid(
    req: Txt2VidRequest,
    current_user: User = Depends(require_permission("ai.generate")),
    db: Session = Depends(get_db),
):
    return await generation_service.create_txt2vid(db, current_user, req)


@router.post("/upload")
async def upload_reference_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("ai.generate")),
):
    from ..utils.file_storage import save_upload
    await _read_reference_upload(file)
    await file.seek(0)
    path = await save_upload(file, "images")
    return {"url": path, "filename": file.filename}


async def _read_reference_upload(file: UploadFile) -> bytes:
    _validate_reference_image_metadata(file.filename, file.content_type)
    content = await file.read(MAX_REFERENCE_IMAGE_BYTES + 1)
    if len(content) > MAX_REFERENCE_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="参考图不能超过 10MB")
    return content


def _decode_reference_payload(img: ImagePayload) -> tuple[bytes, str]:
    content_type = _normalize_content_type(img.mimeType)
    if content_type not in ALLOWED_REFERENCE_IMAGE_MIME_TYPES:
        raise HTTPException(status_code=400, detail="参考图仅支持 JPG、PNG、WEBP")
    try:
        content = base64.b64decode(img.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="参考图数据不是有效的 base64")
    if len(content) > MAX_REFERENCE_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="参考图不能超过 10MB")
    return content, MIME_TO_EXTENSION[content_type]


def _validate_reference_image_metadata(filename: str | None, content_type: str | None) -> None:
    suffix = _file_suffix(filename)
    normalized_content_type = _normalize_content_type(content_type)
    if suffix not in ALLOWED_REFERENCE_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="参考图仅支持 JPG、PNG、WEBP")
    if normalized_content_type and normalized_content_type not in ALLOWED_REFERENCE_IMAGE_MIME_TYPES:
        raise HTTPException(status_code=400, detail="参考图仅支持 JPG、PNG、WEBP")


def _file_suffix(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return f".{filename.rsplit('.', 1)[-1].lower()}"


def _normalize_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()
