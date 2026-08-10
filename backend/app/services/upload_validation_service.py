import stat
import warnings
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_PIXELS = 60_000_000
MAX_OFFICE_ARCHIVE_ENTRIES = 5_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_OFFICE_MEMBER_BYTES = 50 * 1024 * 1024

_IMAGE_FORMATS = {
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".png": {"PNG"},
    ".webp": {"WEBP"},
    ".gif": {"GIF"},
}
_OFFICE_PREFIXES = {
    ".docx": "word/",
    ".pptx": "ppt/",
    ".xlsx": "xl/",
}


def validate_image_content(content: bytes, suffix: str) -> None:
    if not content:
        raise ValueError("Image file is empty")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image dimensions are too large")
                expected = _IMAGE_FORMATS.get(suffix.lower(), set())
                if image_format not in expected:
                    raise ValueError("Image content does not match its extension")
                image.verify()
    except ValueError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
    ) as exc:
        raise ValueError("Image content is invalid") from exc


def normalize_generated_image(content: bytes) -> bytes:
    """Decode a provider image under pixel limits and return canonical PNG bytes."""
    if not content:
        raise ValueError("Generated image is empty")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("Generated image dimensions are too large")
                image.load()
                if image.mode not in {"RGB", "RGBA", "L", "LA"}:
                    image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                return output.getvalue()
    except ValueError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
    ) as exc:
        raise ValueError("Generated image content is invalid") from exc


def validate_video_content(content: bytes, suffix: str) -> None:
    if not content:
        raise ValueError("Video file is empty")
    normalized = suffix.lower()
    if normalized in {".mp4", ".mov"}:
        if b"ftyp" not in content[:64]:
            raise ValueError("Video content does not match its extension")
        return
    if normalized == ".webm" and content[:4] == b"\x1a\x45\xdf\xa3":
        return
    raise ValueError("Video content does not match its extension")


def validate_knowledge_file_content(path: str | Path, suffix: str) -> None:
    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise ValueError("Knowledge file is empty")
    normalized = suffix.lower()
    with candidate.open("rb") as handle:
        header = handle.read(8)
    if normalized == ".pdf":
        if not header.startswith(b"%PDF-"):
            raise ValueError("PDF content is invalid")
        return
    if normalized == ".txt":
        with candidate.open("rb") as handle:
            sample = handle.read(64 * 1024)
        if b"\x00" in sample:
            raise ValueError("Text file contains binary data")
        return
    expected_prefix = _OFFICE_PREFIXES.get(normalized)
    if expected_prefix is None:
        raise ValueError("Unsupported knowledge file type")
    _validate_office_archive(candidate, expected_prefix)


def _validate_office_archive(path: Path, expected_prefix: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_OFFICE_ARCHIVE_ENTRIES:
                raise ValueError("Office archive has too many entries")
            names = {entry.filename.replace("\\", "/") for entry in entries}
            if "[Content_Types].xml" not in names or not any(
                name.startswith(expected_prefix) for name in names
            ):
                raise ValueError("Office file structure is invalid")
            total_size = 0
            for entry in entries:
                _validate_archive_entry(entry)
                total_size += entry.file_size
                if entry.file_size > MAX_OFFICE_MEMBER_BYTES:
                    raise ValueError("Office archive member is too large")
                if total_size > MAX_OFFICE_UNCOMPRESSED_BYTES:
                    raise ValueError("Office archive expands beyond the allowed size")
    except zipfile.BadZipFile as exc:
        raise ValueError("Office file is not a valid ZIP package") from exc


def _validate_archive_entry(entry: zipfile.ZipInfo) -> None:
    normalized = entry.filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not normalized:
        raise ValueError("Office archive contains an unsafe path")
    if entry.flag_bits & 0x1:
        raise ValueError("Encrypted Office archives are not supported")
    unix_mode = (entry.external_attr >> 16) & 0xFFFF
    if unix_mode and stat.S_ISLNK(unix_mode):
        raise ValueError("Office archive links are not supported")
