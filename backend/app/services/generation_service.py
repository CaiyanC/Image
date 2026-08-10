import httpx
import asyncio
import base64
import binascii
from io import BytesIO
from datetime import datetime, date
from urllib.parse import urljoin
from sqlalchemy import func, Date
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from ..models.generation import Generation
from ..models.user import User
from ..schemas.generation import Txt2ImgRequest, Img2ImgRequest, Txt2VidRequest, GenerationStats
from ..utils.file_storage import save_generated_image
from .dmxapi_service import txt2img, img2img, txt2img_gemini, img2img_gemini
from .model_governance_service import ResolvedModel
from .model_governance_service import validate_provider_url
from .upload_validation_service import normalize_generated_image


MAX_IMAGE_DIMENSION = 768
JPEG_QUALITY = 60
IMG2IMG_MAX_RETRIES = 2
TXT2IMG_MAX_RETRIES = 2
MAX_GENERATED_IMAGE_BYTES = 50 * 1024 * 1024
MAX_GENERATED_IMAGE_REDIRECTS = 3


def _compress_image(img_bytes: bytes, filename: str) -> tuple[bytes, str, str]:
    try:
        from PIL import Image
        img = Image.open(BytesIO(img_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        w, h = img.size
        ratio = min(MAX_IMAGE_DIMENSION / max(w, h), 1.0)
        if ratio < 1.0:
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        new_name = f"{filename.rsplit('.', 1)[0]}.jpg" if "." in filename else f"{filename}.jpg"
        return buf.getvalue(), new_name, "image/jpeg"
    except Exception:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}
        return img_bytes, filename, mime_map.get(ext, "image/png")


async def _extract_and_save_b64(data: dict) -> list[str]:
    paths = []
    if data.get("data"):
        for item in data["data"]:
            if item.get("b64_json"):
                try:
                    image_data = base64.b64decode(item["b64_json"], validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("Provider returned invalid base64 image data") from exc
                if len(image_data) > MAX_GENERATED_IMAGE_BYTES:
                    raise ValueError("Provider image exceeds the allowed size")
                path = await save_generated_image(normalize_generated_image(image_data))
                paths.append(path)
            elif item.get("url"):
                image_data = await _download_generated_image(str(item["url"]))
                path = await save_generated_image(normalize_generated_image(image_data))
                paths.append(path)
    return paths


async def _download_generated_image(url: str) -> bytes:
    current_url = url
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        for redirect_count in range(MAX_GENERATED_IMAGE_REDIRECTS + 1):
            current_url = validate_provider_url(current_url, resolve_dns=True)
            async with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location or redirect_count >= MAX_GENERATED_IMAGE_REDIRECTS:
                        raise ValueError("Provider image redirect chain is invalid")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                declared_size = response.headers.get("content-length")
                if declared_size:
                    try:
                        declared_bytes = int(declared_size)
                    except (TypeError, ValueError):
                        declared_bytes = None
                    if declared_bytes is not None and declared_bytes > MAX_GENERATED_IMAGE_BYTES:
                        raise ValueError("Provider image exceeds the allowed size")
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_GENERATED_IMAGE_BYTES:
                        raise ValueError("Provider image exceeds the allowed size")
                return bytes(payload)
    raise ValueError("Provider image could not be downloaded")


async def create_txt2img(db: Session, user: User, req: Txt2ImgRequest, *, resolved_model: ResolvedModel | None):
    params = req.params.model_dump(exclude_none=True) if req.params else {}
    generation = Generation(
        user_id=user.id,
        type="txt2img",
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        model_name=req.model_name,
        parameters=params,
        status="processing",
    )
    db.add(generation)
    db.commit()
    db.refresh(generation)

    try:
        size = params.get("size", "1024x1024")
        n = max(1, min(4, params.get("n", 1)))

        api_format = resolved_model.model.api_format if resolved_model else "openai"

        if api_format == "gemini":
            aspect_ratio = params.get("aspect_ratio", "1:1")
            image_size = params.get("image_size", "1K")
            result = await txt2img_gemini(
                db=db, prompt=req.prompt, model=req.model_name, resolved_model=resolved_model,
                n=n, aspect_ratio=aspect_ratio, image_size=image_size,
            )
            image_paths = await _extract_and_save_b64(result)
            if image_paths:
                generation.result_images = image_paths
                generation.result_image_path = image_paths[0]
                generation.status = "completed"
            else:
                generation.status = "failed"
                generation.error_message = "No image data in response"
        else:
            extra = {}
            for k in ("quality", "output_format", "output_compression", "moderation"):
                if params.get(k) is not None:
                    extra[k] = params[k]

            last_error = None
            for attempt in range(TXT2IMG_MAX_RETRIES + 1):
                try:
                    result = await txt2img(
                        db=db,
                        prompt=req.prompt,
                        model=req.model_name, resolved_model=resolved_model,
                        n=n,
                        size=size,
                        **extra,
                    )
                    image_paths = await _extract_and_save_b64(result)
                    if image_paths:
                        generation.result_images = image_paths
                        generation.result_image_path = image_paths[0]
                        generation.status = "completed"
                    else:
                        generation.status = "failed"
                        generation.error_message = "No image data in response"
                    last_error = None
                    break
                except httpx.HTTPStatusError as e:
                    last_error = e
                    if attempt < TXT2IMG_MAX_RETRIES and e.response.status_code in (408, 429, 500, 502, 503, 504):
                        wait = (attempt + 1) * 5
                        import logging
                        logging.getLogger("uvicorn").warning(f"txt2img attempt {attempt+1} failed ({e.response.status_code}), retrying in {wait}s...")
                        await asyncio.sleep(wait)
                        continue
                    raise
                except Exception:
                    raise

            if last_error:
                raise last_error

    except Exception as e:
        import traceback
        detail = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        generation.status = "failed"
        generation.error_message = detail

    db.commit()
    db.refresh(generation)
    return generation


async def create_img2img(db: Session, user: User, req: Img2ImgRequest, image_data: list[tuple[bytes, str]], *, resolved_model: ResolvedModel | None):
    params = req.params.model_dump(exclude_none=True) if req.params else {}
    generation = Generation(
        user_id=user.id,
        type="img2img",
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        model_name=req.model_name,
        parameters=params,
        status="processing",
    )
    db.add(generation)
    db.commit()
    db.refresh(generation)

    try:
        size = params.get("size", "1024x1024")
        n = max(1, min(4, params.get("n", 1)))

        api_format = resolved_model.model.api_format if resolved_model else "openai"

        if api_format == "gemini":
            import base64
            images_base64 = []
            for img_bytes, filename in image_data:
                mime = "image/jpeg" if filename.lower().endswith(('.jpg', '.jpeg')) else "image/png"
                images_base64.append({
                    "data": base64.b64encode(img_bytes).decode(),
                    "mimeType": mime,
                })

            aspect_ratio = params.get("aspect_ratio", "1:1")
            image_size = params.get("image_size", "1K")
            result = await img2img_gemini(
                db=db, prompt=req.prompt, images=images_base64,
                model=req.model_name, n=n, resolved_model=resolved_model,
                aspect_ratio=aspect_ratio, image_size=image_size,
            )
            image_paths = await _extract_and_save_b64(result)
            if image_paths:
                generation.result_images = image_paths
                generation.result_image_path = image_paths[0]
                generation.status = "completed"
            else:
                generation.status = "failed"
                generation.error_message = "No image data in response"
        else:
            image_files = []
            for idx, (img_bytes, filename) in enumerate(image_data):
                compressed, new_name, mime_type = _compress_image(img_bytes, filename)
                image_files.append((f"ref_{idx}_{new_name}", compressed, mime_type))

            extra = {}
            for k in ("quality", "output_format", "output_compression", "moderation", "background"):
                if params.get(k) is not None:
                    extra[k] = params[k]

            last_error = None
            for attempt in range(IMG2IMG_MAX_RETRIES + 1):
                try:
                    result = await img2img(
                        db=db,
                        prompt=req.prompt,
                        image_files=image_files,
                        model=req.model_name, resolved_model=resolved_model,
                        n=n,
                        size=size,
                        **extra,
                    )
                    image_paths = await _extract_and_save_b64(result)
                    if image_paths:
                        generation.result_images = image_paths
                        generation.result_image_path = image_paths[0]
                        generation.status = "completed"
                    else:
                        generation.status = "failed"
                        generation.error_message = "No image data in response"
                    last_error = None
                    break
                except httpx.HTTPStatusError as e:
                    last_error = e
                    if attempt < IMG2IMG_MAX_RETRIES and e.response.status_code in (408, 429, 500, 502, 503, 504):
                        wait = (attempt + 1) * 5
                        import logging
                        logging.getLogger("uvicorn").warning(f"img2img attempt {attempt+1} failed ({e.response.status_code}), retrying in {wait}s...")
                        await asyncio.sleep(wait)
                        continue
                    raise
                except Exception:
                    raise

            if last_error:
                raise last_error

    except Exception as e:
        import traceback
        detail = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        generation.status = "failed"
        generation.error_message = detail

    db.commit()
    db.refresh(generation)
    return generation


async def create_txt2vid(db: Session, user: User, req: Txt2VidRequest, *, resolved_model: ResolvedModel | None):
    del db, user, req, resolved_model
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Video generation is not available in this deployment",
    )


def get_user_generations(db: Session, user_id: str, skip: int = 0, limit: int = 20, search_query: str = None, date_from: date = None, date_to: date = None):
    query = db.query(Generation).filter(Generation.user_id == user_id)
    
    if search_query:
        query = query.filter(
            Generation.prompt.ilike(f"%{search_query}%") |
            Generation.negative_prompt.ilike(f"%{search_query}%")
        )
    
    if date_from:
        query = query.filter(Generation.created_at >= datetime(date_from.year, date_from.month, date_from.day))
    
    if date_to:
        query = query.filter(Generation.created_at <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59))
    
    return query.order_by(Generation.created_at.desc()).offset(skip).limit(limit).all()


def get_all_generations(db: Session, skip: int = 0, limit: int = 20, search_query: str = None, date_from: date = None, date_to: date = None):
    query = db.query(Generation)
    
    if search_query:
        query = query.filter(
            Generation.prompt.ilike(f"%{search_query}%") |
            Generation.negative_prompt.ilike(f"%{search_query}%")
        )
    
    if date_from:
        query = query.filter(Generation.created_at >= datetime(date_from.year, date_from.month, date_from.day))
    
    if date_to:
        query = query.filter(Generation.created_at <= datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59))
    
    return query.order_by(Generation.created_at.desc()).offset(skip).limit(limit).all()


def get_generation_stats(db: Session, user_id: str = None):
    query = db.query(Generation)
    
    if user_id:
        query = query.filter(Generation.user_id == user_id)
    
    total = query.count()
    
    by_type = {"txt2img": 0, "img2img": 0, "txt2vid": 0}
    type_stats = query.with_entities(Generation.type, func.count(Generation.type)).group_by(Generation.type).all()
    for gen_type, count in type_stats:
        if gen_type in by_type:
            by_type[gen_type] = count
    
    success_count = query.filter(Generation.status == "completed").count()
    success_rate = (success_count / total) * 100 if total > 0 else 0.0
    
    by_date = {}
    date_stats = query.with_entities(func.date(Generation.created_at).label("date"), func.count(Generation.id)).group_by(func.date(Generation.created_at)).order_by(func.date(Generation.created_at).desc()).limit(30).all()
    for date_str, count in date_stats:
        by_date[str(date_str)] = count
    
    return GenerationStats(
        total=total,
        by_type=by_type,
        by_date=by_date,
        success_rate=round(success_rate, 1)
    )


def get_generation_by_id(db: Session, generation_id: str, user_id: str = None):
    query = db.query(Generation).filter(Generation.id == generation_id)
    
    if user_id:
        query = query.filter(Generation.user_id == user_id)
    
    gen = query.first()
    
    if not gen:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")
    return gen


def delete_generation(db: Session, generation_id: str, user_id: str):
    gen = get_generation_by_id(db, generation_id, user_id)
    db.delete(gen)
    db.commit()
