import uuid
import os
import aiofiles
from fastapi import UploadFile
from ..core.config import settings


async def save_upload(file: UploadFile, subdir: str) -> str:
    os.makedirs(os.path.join(settings.UPLOAD_DIR, subdir), exist_ok=True)

    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "png"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(settings.UPLOAD_DIR, subdir, filename)

    async with aiofiles.open(filepath, "wb") as f:
        content = await file.read()
        await f.write(content)

    return f"/uploads/{subdir}/{filename}"


async def save_generated_image(image_data: bytes, filename_prefix: str = "gen") -> str:
    os.makedirs(settings.GENERATED_DIR, exist_ok=True)

    filename = f"{filename_prefix}_{uuid.uuid4().hex[:12]}.png"
    filepath = os.path.join(settings.GENERATED_DIR, filename)

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(image_data)

    return f"/uploads/generated/{filename}"
