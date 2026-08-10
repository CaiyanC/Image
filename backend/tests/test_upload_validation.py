import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app.services import upload_validation_service
from app.services.upload_validation_service import normalize_generated_image
from app.services.file_ingestion_service import (
    ExtractedSection,
    MAX_EXTRACTED_SECTIONS,
    _validate_extracted_sections,
)


def _image_bytes(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (3, 2), color="blue").save(buffer, format=image_format)
    return buffer.getvalue()


def test_image_content_must_be_decodable_and_match_extension():
    upload_validation_service.validate_image_content(_image_bytes("PNG"), ".png")
    with pytest.raises(ValueError, match="invalid"):
        upload_validation_service.validate_image_content(b"<script>alert(1)</script>", ".png")
    with pytest.raises(ValueError, match="extension"):
        upload_validation_service.validate_image_content(_image_bytes("PNG"), ".jpg")


def test_generated_images_are_decoded_and_normalized_to_png():
    normalized = normalize_generated_image(_image_bytes("JPEG"))
    assert normalized.startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="invalid"):
        normalize_generated_image(b"not an image")


def test_video_content_requires_a_matching_container_signature():
    upload_validation_service.validate_video_content(b"\x00\x00\x00\x18ftypisom" + b"x" * 20, ".mp4")
    upload_validation_service.validate_video_content(b"\x1a\x45\xdf\xa3" + b"x" * 20, ".webm")
    with pytest.raises(ValueError, match="extension"):
        upload_validation_service.validate_video_content(b"MZ" + b"x" * 100, ".mp4")


def _office_file(path: Path, member: str, payload: bytes = b"<xml/>") -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr(member, payload)


def test_office_archive_structure_and_expansion_are_bounded(tmp_path):
    valid = tmp_path / "valid.docx"
    _office_file(valid, "word/document.xml")
    upload_validation_service.validate_knowledge_file_content(valid, ".docx")

    oversized = tmp_path / "oversized.docx"
    _office_file(oversized, "word/document.xml", b"x" * 64)
    with patch.object(upload_validation_service, "MAX_OFFICE_UNCOMPRESSED_BYTES", 32):
        with pytest.raises(ValueError, match="expands"):
            upload_validation_service.validate_knowledge_file_content(oversized, ".docx")

    unsafe = tmp_path / "unsafe.docx"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", b"<xml/>")
        archive.writestr("../escape.xml", b"bad")
    with pytest.raises(ValueError, match="unsafe path"):
        upload_validation_service.validate_knowledge_file_content(unsafe, ".docx")


def test_pdf_and_text_headers_are_checked(tmp_path):
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"not a pdf")
    with pytest.raises(ValueError, match="PDF"):
        upload_validation_service.validate_knowledge_file_content(fake_pdf, ".pdf")

    binary_text = tmp_path / "binary.txt"
    binary_text.write_bytes(b"text\x00binary")
    with pytest.raises(ValueError, match="binary"):
        upload_validation_service.validate_knowledge_file_content(binary_text, ".txt")


def test_extracted_section_count_and_text_size_are_bounded():
    too_many = [ExtractedSection(text="x", meta={}) for _ in range(MAX_EXTRACTED_SECTIONS + 1)]
    with pytest.raises(ValueError, match="sections"):
        _validate_extracted_sections(too_many)

    with patch("app.services.file_ingestion_service.MAX_EXTRACTED_TEXT_CHARS", 3):
        with pytest.raises(ValueError, match="allowed size"):
            _validate_extracted_sections([ExtractedSection(text="four", meta={})])
