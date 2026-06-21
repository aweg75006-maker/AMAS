from io import BytesIO

import pytest
from fastapi import UploadFile

from app.core.exceptions import AppError
from app.services.upload_security import (
    ensure_safe_destination,
    sanitize_filename,
    save_upload_file,
)


def make_upload(
    filename: str,
    content: bytes = b"%PDF-1.4",
    content_type: str = "application/pdf",
) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
        headers={"content-type": content_type},
    )


def test_sanitize_filename_removes_path_components():
    assert sanitize_filename("../../evil.pdf") == "evil.pdf"
    assert sanitize_filename("a b 中文.pdf") == "a_b_.pdf"


def test_sanitize_filename_rejects_empty_name():
    with pytest.raises(AppError) as exc:
        sanitize_filename("../")

    assert exc.value.code == "INVALID_FILENAME"


def test_safe_destination_stays_inside_upload_dir(tmp_path):
    destination = ensure_safe_destination(tmp_path, "safe.pdf")

    assert destination.parent == tmp_path.resolve()
    assert destination.name == "safe.pdf"


def test_save_upload_file_prefixes_unique_name_and_writes_file(tmp_path):
    upload = make_upload("../../report.pdf", b"%PDF-1.4 test")

    saved_path = save_upload_file(upload, tmp_path)

    assert saved_path.parent == tmp_path.resolve()
    assert saved_path.name.endswith("_report.pdf")
    assert saved_path.read_bytes() == b"%PDF-1.4 test"


def test_save_upload_file_rejects_large_file_and_removes_partial(tmp_path, monkeypatch):
    from app.services import upload_security

    monkeypatch.setattr(upload_security.settings, "upload_max_file_size_bytes", 4)
    upload = make_upload("big.pdf", b"12345")

    with pytest.raises(AppError) as exc:
        save_upload_file(upload, tmp_path)

    assert exc.value.code == "FILE_TOO_LARGE"
    assert list(tmp_path.iterdir()) == []
