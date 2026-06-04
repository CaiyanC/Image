from datetime import datetime
from typing import Optional, Dict, List
from pydantic import BaseModel
from .common import UuidStr


class GenerationParams(BaseModel):
    size: Optional[str] = "1024x1024"
    n: Optional[int] = 1
    quality: Optional[str] = "medium"
    output_format: Optional[str] = "png"
    output_compression: Optional[int] = None
    moderation: Optional[str] = "low"
    background: Optional[str] = None
    seed: Optional[int] = None
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None

    model_config = {"protected_namespaces": ()}


class Txt2ImgRequest(BaseModel):
    prompt: str
    model_name: str = "flux-schnell"
    negative_prompt: Optional[str] = None
    params: Optional[GenerationParams] = None

    model_config = {"protected_namespaces": ()}


class Img2ImgRequest(BaseModel):
    prompt: str
    model_name: str = "flux-schnell"
    negative_prompt: Optional[str] = None
    params: Optional[GenerationParams] = None

    model_config = {"protected_namespaces": ()}


class ImagePayload(BaseModel):
    data: str
    mimeType: str = "image/png"


class Img2ImgGeminiRequest(BaseModel):
    prompt: str
    model_name: str = "gemini-3.1-flash-image-preview"
    negative_prompt: Optional[str] = None
    params: Optional[GenerationParams] = None
    images: List[ImagePayload]

    model_config = {"protected_namespaces": ()}


class Txt2VidRequest(BaseModel):
    prompt: str
    model_name: str = "cogvideox"
    negative_prompt: Optional[str] = None
    params: Optional[GenerationParams] = None

    model_config = {"protected_namespaces": ()}


class GenerationResponse(BaseModel):
    id: UuidStr
    user_id: UuidStr
    type: str
    prompt: str
    negative_prompt: Optional[str] = None
    source_image_path: Optional[str] = None
    result_image_path: Optional[str] = None
    result_images: Optional[list] = None
    result_video_path: Optional[str] = None
    model_name: str
    parameters: Optional[dict] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class GenerationStats(BaseModel):
    total: int = 0
    by_type: Dict[str, int] = {"txt2img": 0, "img2img": 0, "txt2vid": 0}
    by_date: Dict[str, int] = {}
    success_rate: float = 0.0

    model_config = {"protected_namespaces": ()}


class ModelInfo(BaseModel):
    id: UuidStr
    name: str
    type: str
    description: str = ""
    api_format: str = "openai"

    model_config = {"from_attributes": True, "protected_namespaces": ()}