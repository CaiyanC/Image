"""Read-only MCP-facing access to the visual asset library.

The MCP adapter deliberately sits on top of the existing ``product_assets``
model and upload storage.  It never creates, updates, or deletes assets.  The
default read policy is the asset publication boundary: approved, usable,
authorized, public, AI-reference-usable, and not an unresolved duplicate.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.product_asset import ProductAsset
from . import asset_service


class ProductAssetMcpError(ValueError):
    """A safe, user-facing error returned by the local MCP adapter."""


class ProductAssetMcpService:
    """Expose approved product assets without exposing filesystem paths."""

    def __init__(
        self,
        db: Session,
        *,
        upload_dir: str | Path | None = None,
        include_unreviewed: bool = False,
    ) -> None:
        self.db = db
        self.upload_root = Path(upload_dir or settings.UPLOAD_DIR).resolve()
        self.include_unreviewed = include_unreviewed

    def list_assets(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        limit = _bounded_limit(arguments.get("limit", 20))
        # Apply the publication boundary before the database limit.  Filtering
        # only after a fixed candidate page lets a large pending/invalid tail
        # hide approved assets that are later in the catalogue.
        review_status = None if self.include_unreviewed else "approved"
        quality_status = None if self.include_unreviewed else "usable"
        rows = asset_service.search_assets(
            self.db,
            sku=_optional_text(arguments.get("sku")),
            category=_optional_text(arguments.get("category_code")),
            channel=_optional_text(arguments.get("channel")),
            review_status=review_status,
            quality_status=quality_status,
            expression_tags=_string_list(arguments.get("expression_tags")),
            selling_point_tags=_string_list(arguments.get("selling_point_tags")),
            scene_tags=_string_list(arguments.get("scene_tags")),
            mood_tags=_string_list(arguments.get("mood_tags")),
            limit=limit,
        )
        return [
            self._metadata(asset)
            for asset in rows
            if self._is_readable(asset)
        ][:limit]

    def read_asset(
        self,
        sku: str,
        asset_id: str,
        *,
        variant: str = "original",
        include_image: bool = True,
    ) -> dict[str, Any]:
        asset = self._get_readable_asset(sku, asset_id)
        metadata = self._metadata(asset)
        if not include_image:
            return {"metadata": metadata, "data": None, "mime_type": None}

        file_path = self._resolve_asset_file(asset, variant)
        file_size = file_path.stat().st_size
        if file_size > 20 * 1024 * 1024:
            raise ProductAssetMcpError("素材超过 MCP 单次读取大小限制（20MB）")
        mime_type = asset.mime_type or mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return {
            "metadata": metadata,
            "data": file_path.read_bytes(),
            "mime_type": mime_type,
            "variant": variant,
        }

    def read_resource(self, uri: str) -> dict[str, Any]:
        sku, asset_id, variant = parse_asset_resource_uri(uri)
        result = self.read_asset(sku, asset_id, variant=variant)
        return {"uri": uri, **result}

    def resource_uri(self, sku: str, asset_id: str, *, variant: str = "original") -> str:
        uri = f"caiyan://product-assets/{quote(sku, safe='-_.')}/{quote(asset_id, safe='-_.')}"
        if variant != "original":
            uri += f"?variant={quote(variant, safe='-_.')}"
        return uri

    def _get_readable_asset(self, sku: str, asset_id: str) -> ProductAsset:
        clean_sku = _required_text(sku, "sku")
        clean_asset_id = _required_text(asset_id, "asset_id")
        asset = (
            self.db.query(ProductAsset)
            .filter(ProductAsset.sku == clean_sku, ProductAsset.id == clean_asset_id)
            .first()
        )
        if not asset or not self._is_readable(asset):
            raise ProductAssetMcpError("未找到可读取的素材")
        return asset

    def _is_readable(self, asset: ProductAsset) -> bool:
        if asset.quality_status in {"invalid", "archived"}:
            return False
        if asset.duplicate_status == "suspected_duplicate":
            return False
        if self.include_unreviewed:
            return True
        # MCP is an AI-facing read surface, so approval alone is not a
        # publication grant. Keep the three independent release decisions
        # explicit: the asset must be reviewed, authorized for use, publicly
        # published, and marked safe as an AI reference.
        authorization_status = str(asset.authorization_status or "").strip().lower()
        return (
            asset.review_status == "approved"
            and asset.quality_status == "usable"
            and authorization_status not in {"", "unknown", "denied", "revoked"}
            and bool(asset.is_public)
            and bool(asset.ai_reference_usable)
        )

    def _metadata(self, asset: ProductAsset) -> dict[str, Any]:
        payload = asset_service.model_to_dict(asset)
        for key in ("created_at", "updated_at"):
            value = payload.get(key)
            if value is not None and hasattr(value, "isoformat"):
                payload[key] = value.isoformat()
        payload["resource_uri"] = self.resource_uri(asset.sku, asset.id)
        if asset.thumbnail_url:
            payload["thumbnail_resource_uri"] = self.resource_uri(asset.sku, asset.id, variant="thumbnail")
        return payload

    def _resolve_asset_file(self, asset: ProductAsset, variant: str) -> Path:
        if variant not in {"original", "thumbnail"}:
            raise ProductAssetMcpError("variant 只能是 original 或 thumbnail")
        raw_url = asset.thumbnail_url if variant == "thumbnail" else asset.url
        if not raw_url:
            raise ProductAssetMcpError("该素材没有可读取的文件")
        normalized = str(raw_url).split("?", 1)[0].replace("\\", "/")
        parsed = urlparse(normalized)
        normalized = parsed.path if parsed.scheme in {"http", "https"} else normalized
        if not normalized.startswith("/uploads/assets/"):
            raise ProductAssetMcpError("素材地址不在 product_assets 存储范围内")
        parts = Path(normalized).parts
        if ".." in parts:
            raise ProductAssetMcpError("素材地址非法")
        relative = normalized.removeprefix("/uploads/").lstrip("/")
        candidate = (self.upload_root / relative).resolve()
        try:
            candidate.relative_to(self.upload_root)
        except ValueError as exc:
            raise ProductAssetMcpError("素材地址越过存储根目录") from exc
        if not candidate.is_file():
            raise ProductAssetMcpError("素材文件不存在")
        return candidate


def parse_asset_resource_uri(uri: str) -> tuple[str, str, str]:
    parsed = urlparse(str(uri or ""))
    if parsed.scheme != "caiyan" or parsed.netloc != "product-assets":
        raise ProductAssetMcpError("不支持的素材资源 URI")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ProductAssetMcpError("素材资源 URI 缺少 SKU 或素材 ID")
    variant = (parse_qs(parsed.query).get("variant") or ["original"])[0]
    return parts[0], parts[1], variant


def _bounded_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ProductAssetMcpError("limit 必须是整数") from exc
    if not 1 <= limit <= 50:
        raise ProductAssetMcpError("limit 必须在 1 到 50 之间")
    return limit


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ProductAssetMcpError(f"{field} 不能为空")
    return text


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProductAssetMcpError("标签过滤条件必须是数组")
    return [str(item).strip() for item in value if str(item).strip()]
