"""Upload validation: extension allowlist, content sniffing, and ZIP safety.

The browser-supplied filename and MIME type are untrusted. Only the
extension allowlist plus the bytes themselves decide whether a file is
accepted, and the stored MIME type is derived from the validated extension
instead of being echoed from the request (SECURITY.md).

ZIP containers (`.docx`, `.xlsx`, `.pptx`, `.odt`) get a bomb guard before
any parser opens them: entry count, per-entry size, total uncompressed size,
compression ratio, and encryption are all bounded.
"""
from __future__ import annotations

import io
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

MAX_FILENAME_LENGTH = 120
MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_ENTRY_BYTES = 32 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ZIP_RATIO = 100

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = b"PK\x03\x04"

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".rtf": "application/rtf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

# Office Open XML / OpenDocument containers carry a required part. Checking it
# is stronger than a bare ZIP signature and catches renamed archives.
ZIP_REQUIRED_ENTRY = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
    ".pptx": "ppt/presentation.xml",
    ".odt": "content.xml",
}

IMAGE_MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
}

TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".rtf"}
OLE_EXTENSIONS = {".doc", ".xls", ".ppt"}


class UploadValidationError(ValueError):
    """The upload cannot be accepted; the message is safe to show."""


class UploadTooLarge(UploadValidationError):
    """The upload exceeds the effective per-file limit."""


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    extension: str
    mime_type: str


def sanitize_filename(name: str) -> str:
    """Return a display-safe basename with a bounded length."""
    base = PurePath((name or "").replace("\\", "/")).name
    base = unicodedata.normalize("NFC", base)
    base = "".join(
        char
        for char in base
        if char not in {'"', "'", "/", "\\"} and ord(char) >= 32
    ).strip(" .")
    if not base:
        return "file"
    if len(base) <= MAX_FILENAME_LENGTH:
        return base
    suffix = PurePath(base).suffix
    keep = max(1, MAX_FILENAME_LENGTH - len(suffix))
    return f"{base[:keep]}{suffix}"


def validate_upload(
    filename: str,
    content: bytes,
    *,
    allowed_extensions: tuple[str, ...],
    max_bytes: int,
) -> ValidatedUpload:
    safe_name = sanitize_filename(filename)
    extension = PurePath(safe_name).suffix.lower()
    allowed = {item.lower() for item in allowed_extensions}
    if extension not in allowed:
        shown = extension or "no extension"
        raise UploadValidationError(f"Files of type {shown} are not accepted.")
    if not content:
        raise UploadValidationError("The uploaded file is empty.")
    if len(content) > max_bytes:
        raise UploadTooLarge("The uploaded file is too large.")
    _check_content(extension, content)
    return ValidatedUpload(
        filename=safe_name,
        extension=extension,
        mime_type=MIME_TYPES.get(extension, "application/octet-stream"),
    )


def assert_safe_docx(content: bytes) -> None:
    """Validate a DOCX before handing it to docxtpl/python-docx."""
    _check_zip(content, ZIP_REQUIRED_ENTRY[".docx"])


def _check_content(extension: str, content: bytes) -> None:
    if extension in ZIP_REQUIRED_ENTRY:
        _check_zip(content, ZIP_REQUIRED_ENTRY[extension])
        return
    if extension in OLE_EXTENSIONS:
        _require_magic(content, (OLE_MAGIC,), extension)
        return
    if extension in IMAGE_MAGIC:
        _require_magic(content, IMAGE_MAGIC[extension], extension)
        return
    if extension == ".webp":
        if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
            raise UploadValidationError("The file content is not a valid .webp image.")
        return
    if extension == ".pdf":
        _require_magic(content, (b"%PDF-",), extension)
        return
    if extension == ".rtf":
        if not content.lstrip().startswith(b"{\\rtf"):
            raise UploadValidationError("The file content is not a valid .rtf document.")
        return
    if extension in TEXT_EXTENSIONS:
        _check_text(content, extension)


def _require_magic(content: bytes, signatures: tuple[bytes, ...], extension: str) -> None:
    if not any(content.startswith(signature) for signature in signatures):
        raise UploadValidationError(
            f"The file content does not match its {extension} extension."
        )


def _check_text(content: bytes, extension: str) -> None:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            text = content.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise UploadValidationError(
                f"The file content is not valid text for {extension}."
            ) from exc
    else:
        if b"\x00" in content:
            raise UploadValidationError(
                f"The file content is not valid text for {extension}."
            )
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadValidationError(
                f"The file content is not valid UTF-8 text for {extension}."
            ) from exc
    controls = sum(
        1 for char in text if ord(char) < 32 and char not in {"\t", "\n", "\r"}
    )
    if text and controls / len(text) > 0.01:
        raise UploadValidationError(
            f"The file content is not valid text for {extension}."
        )


def _check_zip(content: bytes, required_entry: str) -> None:
    if not content.startswith(ZIP_MAGIC):
        raise UploadValidationError("The file content is not a valid Office document.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise UploadValidationError(
                    "The document contains too many internal files."
                )
            total = 0
            for entry in entries:
                if entry.flag_bits & 0x1:
                    raise UploadValidationError(
                        "Encrypted Office documents are not supported."
                    )
                if entry.file_size > MAX_ZIP_ENTRY_BYTES:
                    raise UploadValidationError(
                        "The document contains an oversized internal file."
                    )
                total += entry.file_size
            if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise UploadValidationError(
                    "The document expands to more data than this deployment accepts."
                )
            if content and total > len(content) * MAX_ZIP_RATIO:
                raise UploadValidationError(
                    "The document has an unsafe compression ratio."
                )
            names = {entry.filename.replace("\\", "/") for entry in entries}
            if required_entry not in names:
                raise UploadValidationError(
                    "The file is not a valid Office document: "
                    f"missing {required_entry}."
                )
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise UploadValidationError("The file content is not a valid Office document.") from exc
