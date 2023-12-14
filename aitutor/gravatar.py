import hashlib
from dataclasses import dataclass


def get_email_hash(email: str) -> str:
    """Return the hash of an email address."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def get_gravatar_image(email: str, size: int | None = None) -> str:
    """Return the URL of a Gravatar image."""
    url = f"https://www.gravatar.com/avatar/{get_email_hash(email)}"
    if size is not None:
        url += f"?s={size}"
    return url


@dataclass
class Profile:
    email: str
    gravatar_id: str
    image_url: str

    @classmethod
    def from_email(cls, email: str) -> "Profile":
        """Return a profile from an email address."""
        hashed = get_email_hash(email)
        return cls(
            email=email,
            gravatar_id=hashed,
            image_url=get_gravatar_image(email),
        )
