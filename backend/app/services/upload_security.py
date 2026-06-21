import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import AppError


SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def allowed_extensions() -> set[str]:
    return {
        ext.strip().lower()
        for ext in settings.upload_allowed_extensions.split(",")
        if ext.strip()
    }


def allowed_content_types() -> set[str]:
    return {
        content_type.strip().lower()
        for content_type in settings.upload_allowed_content_types.split(",")
        if content_type.strip()
    }


def sanitize_filename(filename: str | None) -> str:
    raw_name = Path(filename or "").name.strip()
    if not raw_name:
        raise AppError(
            code="INVALID_FILENAME",
            message="文件名不能为空",
            status_code=400,
        )

    sanitized = SAFE_FILENAME_PATTERN.sub("_", raw_name)
    sanitized = sanitized.strip("._")
    if not sanitized:
        raise AppError(
            code="INVALID_FILENAME",
            message="文件名无效",
            status_code=400,
        )
    return sanitized


def validate_upload_batch(files: list[UploadFile]) -> None:
    if not files:
        raise AppError(
            code="NO_FILES_UPLOADED",
            message="请至少上传 1 个文件",
            status_code=400,
        )

    if len(files) > settings.upload_max_files:
        raise AppError(
            code="TOO_MANY_FILES",
            message=f"一次最多只能上传 {settings.upload_max_files} 个文件",
            status_code=400,
            details={
                "max_files": settings.upload_max_files,
                "actual_files": len(files),
            },
        )


def validate_upload_files(files: list[UploadFile]) -> None:
    validate_upload_batch(files)
    for file in files:
        safe_name = sanitize_filename(file.filename)
        validate_upload_file(file, safe_name)


def validate_upload_file(file: UploadFile, safe_name: str) -> None:
    extension = Path(safe_name).suffix.lower()
    if extension not in allowed_extensions():
        raise AppError(
            code="UNSUPPORTED_FILE_TYPE",
            message="不支持的文件类型",
            status_code=400,
            details={
                "filename": safe_name,
                "extension": extension,
                "allowed_extensions": sorted(allowed_extensions()),
            },
        )

    content_type = (file.content_type or "").lower()
    if content_type and content_type not in allowed_content_types():
        raise AppError(
            code="UNSUPPORTED_CONTENT_TYPE",
            message="不支持的文件 MIME 类型",
            status_code=400,
            details={
                "filename": safe_name,
                "content_type": content_type,
                "allowed_content_types": sorted(allowed_content_types()),
            },
        )


def ensure_safe_destination(upload_dir: str | Path, filename: str) -> Path:
    base_dir = Path(upload_dir).resolve()
    destination = (base_dir / filename).resolve()
    if base_dir != destination.parent:
        raise AppError(
            code="INVALID_UPLOAD_PATH",
            message="上传路径无效",
            status_code=400,
        )
    return destination


def save_upload_file(file: UploadFile, upload_dir: str | Path) -> Path:
    safe_name = sanitize_filename(file.filename)
    validate_upload_file(file, safe_name)

    unique_name = f"{uuid4().hex}_{safe_name}"
    destination = ensure_safe_destination(upload_dir, unique_name)
    destination.parent.mkdir(parents=True, exist_ok=True)

    max_size = settings.upload_max_file_size_bytes
    total_size = 0

    try:
        with destination.open("wb") as buffer:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_size:
                    buffer.close()
                    destination.unlink(missing_ok=True)
                    raise AppError(
                        code="FILE_TOO_LARGE",
                        message="上传文件超过大小限制",
                        status_code=413,
                        details={
                            "filename": safe_name,
                            "max_size_bytes": max_size,
                        },
                    )
                buffer.write(chunk)
    finally:
        file.file.seek(0)

    return destination


def save_upload_batch(files: list[UploadFile], upload_dir: str | Path) -> list[str]:
    validate_upload_files(files)
    return [str(save_upload_file(file, upload_dir)) for file in files]
