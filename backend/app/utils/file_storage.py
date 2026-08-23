import uuid
import os
import aiofiles
from fastapi import UploadFile
from ..core.config import settings


async def save_upload(file: UploadFile, subdir: str) -> str:
    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "png"
    return await save_bytes(await file.read(), subdir, ext)


async def save_bytes(content: bytes, subdir: str, extension: str, filename_prefix: str = "") -> str:
    target_dir = os.path.abspath(os.path.join(settings.UPLOAD_DIR, subdir))
    upload_root = os.path.abspath(settings.UPLOAD_DIR)
    if os.path.commonpath([target_dir, upload_root]) != upload_root:
        raise ValueError("Invalid upload subdirectory")
    os.makedirs(target_dir, exist_ok=True)

    ext = str(extension or "png").lower().lstrip(".")
    prefix = f"{filename_prefix}_" if filename_prefix else ""
    filename = f"{prefix}{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(target_dir, filename)
    temporary_path = f"{filepath}.{uuid.uuid4().hex}.part"

    try:
        async with aiofiles.open(temporary_path, "wb") as f:
            await f.write(content)
        os.replace(temporary_path, filepath)
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass

    normalized_subdir = subdir.replace("\\", "/").strip("/")
    return f"/uploads/{normalized_subdir}/{filename}"


async def save_generated_image(image_data: bytes, filename_prefix: str = "gen") -> str:
    os.makedirs(settings.GENERATED_DIR, exist_ok=True)

    filename = f"{filename_prefix}_{uuid.uuid4().hex[:12]}.png"
    filepath = os.path.join(settings.GENERATED_DIR, filename)
    temporary_path = f"{filepath}.{uuid.uuid4().hex}.part"

    try:
        async with aiofiles.open(temporary_path, "wb") as f:
            await f.write(image_data)
        os.replace(temporary_path, filepath)
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass

    return f"/uploads/generated/{filename}"
