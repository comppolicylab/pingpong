import io

from fastapi import UploadFile

from pingpong.files import _normalize_upload_content_type


def _upload(filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(b"content"),
        filename=filename,
        headers={"content-type": content_type},
    )


def test_normalize_upload_content_type_uses_known_extension_for_generic_mime():
    upload = _upload("notes.md", "application/octet-stream")

    assert _normalize_upload_content_type(upload) == "text/markdown"


def test_normalize_upload_content_type_keeps_matching_generic_extension():
    upload = _upload("model.pkl", "application/octet-stream")

    assert _normalize_upload_content_type(upload) == "application/octet-stream"


def test_normalize_upload_content_type_keeps_supported_reported_mime():
    upload = _upload("notes.unknown", "text/markdown")

    assert _normalize_upload_content_type(upload) == "text/markdown"
