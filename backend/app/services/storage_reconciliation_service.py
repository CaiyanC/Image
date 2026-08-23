"""Read-only by default inventory and reconciliation for managed uploads."""

import hashlib
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..core.config import BACKEND_ROOT, PROJECT_ROOT, settings
from ..models.ai_generated_asset import AiGeneratedAsset
from ..models.generation import Generation
from ..models.product_asset import ProductAsset
from ..models.product_associations import ProductCertification
from ..models.product_media import ProductMedia


MANAGED_SCOPES = ("assets", "images", "videos", "generated", "reference-images")


def reconcile_upload_storage(
    db: Session,
    *,
    apply_cleanup: bool = False,
    migrate_legacy: bool = False,
    minimum_age_hours: int = 24,
) -> dict:
    root = Path(settings.UPLOAD_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    references = _collect_references(db, root)
    legacy_root = _legacy_root(root)
    migrated: list[str] = []
    missing: list[str] = []
    legacy_available: list[str] = []
    errors: list[str] = []

    for relative in sorted(references):
        destination = root / relative
        if destination.is_file():
            continue
        source = legacy_root / relative if legacy_root else None
        if source and source.is_file():
            legacy_available.append(relative.as_posix())
            if migrate_legacy:
                try:
                    _verified_copy(source, destination)
                    migrated.append(relative.as_posix())
                except OSError as exc:
                    errors.append(f"migrate {relative.as_posix()}: {exc}")
            continue
        missing.append(relative.as_posix())

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, minimum_age_hours))
    orphan_files: list[dict] = []
    removed: list[str] = []
    for scope in MANAGED_SCOPES:
        scope_root = root / scope
        if not scope_root.is_dir():
            continue
        for path in scope_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if relative in references:
                continue
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            old_enough = modified <= cutoff
            orphan_files.append({
                "path": relative.as_posix(),
                "size_bytes": stat.st_size,
                "modified_at": modified.isoformat(),
                "eligible_for_cleanup": old_enough,
            })
            if apply_cleanup and old_enough:
                try:
                    path.unlink()
                    removed.append(relative.as_posix())
                except OSError as exc:
                    errors.append(f"remove {relative.as_posix()}: {exc}")

    return {
        "upload_root": str(root),
        "dry_run": not (apply_cleanup or migrate_legacy),
        "reference_count": len(references),
        "missing_references": missing,
        "legacy_available": legacy_available,
        "migrated": migrated,
        "orphan_files": orphan_files,
        "removed": removed,
        "errors": errors,
    }


def _collect_references(db: Session, root: Path) -> set[Path]:
    table_names = set(inspect(db.bind).get_table_names())
    values: list[str | None] = []
    if ProductAsset.__tablename__ in table_names:
        for url, thumbnail in db.query(ProductAsset.url, ProductAsset.thumbnail_url).all():
            values.extend((url, thumbnail))
    if ProductMedia.__tablename__ in table_names:
        for path, url in db.query(ProductMedia.file_path, ProductMedia.file_url).all():
            values.extend((path, url))
    if AiGeneratedAsset.__tablename__ in table_names:
        values.extend(row[0] for row in db.query(AiGeneratedAsset.generated_file_path).all())
    if ProductCertification.__tablename__ in table_names:
        values.extend(row[0] for row in db.query(ProductCertification.certification_file_path).all())
    if Generation.__tablename__ in table_names:
        for generation in db.query(Generation).all():
            values.extend((generation.source_image_path, generation.result_image_path, generation.result_video_path))
            if isinstance(generation.result_images, list):
                values.extend(item for item in generation.result_images if isinstance(item, str))
            elif isinstance(generation.result_images, dict):
                values.extend(item for item in generation.result_images.values() if isinstance(item, str))

    references: set[Path] = set()
    for value in values:
        relative = _relative_upload_path(value, root)
        if relative and relative.parts and relative.parts[0] in MANAGED_SCOPES:
            references.add(relative)
    return references


def _relative_upload_path(value: str | None, root: Path) -> Path | None:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        raw = urlparse(raw).path
    if raw.startswith("/uploads/"):
        relative = Path(raw.removeprefix("/uploads/").lstrip("/"))
    else:
        candidate = Path(raw).resolve()
        if candidate != root and root not in candidate.parents:
            return None
        relative = candidate.relative_to(root)
    if ".." in relative.parts:
        return None
    return relative


def _legacy_root(root: Path) -> Path | None:
    if root.parent != Path(BACKEND_ROOT).resolve():
        return None
    candidate = (Path(PROJECT_ROOT) / root.name).resolve()
    return candidate if candidate != root else None


def _verified_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.migration")
    try:
        shutil.copy2(source, temporary)
        if source.stat().st_size != temporary.stat().st_size or _checksum(source) != _checksum(temporary):
            raise OSError("checksum verification failed")
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
