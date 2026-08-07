from urllib.parse import quote


def content_disposition(disposition_type: str, filename: str) -> str:
    """Build a Content-Disposition value that is safe for ASGI response headers."""
    encoded_filename = quote(filename, safe="")
    if encoded_filename == filename:
        return f'{disposition_type}; filename="{filename}"'
    return f"{disposition_type}; filename*=utf-8''{encoded_filename}"
