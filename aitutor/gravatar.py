import hashlib


def get_email_hash(email: str) -> str:
    """Return the hash of an email address."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def get_gravatar_image(email: str, size: int | None = None) -> str:
    """Return the URL of a Gravatar image."""
    url = f"https://www.gravatar.com/avatar/{get_email_hash(email)}"
    if size is not None:
        url += f"?s={size}"
    return url
