from datetime import timedelta
from typing import cast
import re

from fastapi.responses import RedirectResponse
import jwt
from jwt.exceptions import PyJWTError

from .config import config, AuthnSettings
from .now import NowFn, utcnow
from .schemas import AuthToken, SessionToken


def encode_session_token(
    user_id: int, expiry: int = 86_400, nowfn: NowFn = utcnow
) -> str:
    """Encodes the session token as a JWT.

    Args:
        user_id (int): User ID
        expiry (int, optional): Expiry in seconds. Defaults to 86400 (1 day).
        nowfn (NowFn, optional): Function to get the current time. Defaults to utcnow.

    Returns:
        str: Encoded session token JWT
    """
    return encode_auth_token(str(user_id), expiry, nowfn=nowfn)


def decode_session_token(token: str, nowfn: NowFn = utcnow) -> SessionToken:
    """Decodes the Session Token.

    Args:
        token (str): Encoded session token JWT
        nowfn (NowFn, optional): Function to get the current time. Defaults to utcnow.

    Returns:
        SessionToken: Session Token
    """
    auth_token = decode_auth_token(token, nowfn=nowfn)
    return SessionToken(**auth_token.model_dump())


def encode_auth_token(
    sub: str,
    expiry: int = 600,
    nowfn: NowFn = utcnow,
) -> str:
    """Generates the Auth Token.

    Args:
        sub (str): A user-provided string to provide as the `sub` parameter for `AuthToken` generation.
        expiry (int, optional): Expiry in seconds. Defaults to 600.
        nowfn (NowFn, optional): Function to get the current time. Defaults to utcnow.

    Returns:
        str: Auth Token
    """
    if expiry < 1:
        raise ValueError("expiry must be greater than 1 second")

    now = nowfn()
    exp = now + timedelta(seconds=expiry)
    tok = AuthToken(
        iat=int(now.timestamp()),
        exp=int(exp.timestamp()),
        sub=sub,
    )

    secret = config.auth.secret_keys[0]

    # For some reason mypy is wrong and thinks this is a bytes object. It is
    # actually a str in PyJWT:
    # https://github.com/jpadilla/pyjwt/blob/2.8.0/jwt/api_jwt.py#L52
    return cast(
        str,
        jwt.encode(
            tok.model_dump(),
            secret.key,
            algorithm=secret.algorithm,
        ),
    )


class TimeException(Exception):
    def __init__(self, detail: str = "", user_id: str = ""):
        self.user_id = user_id
        self.detail = detail


def decode_auth_token(token: str, nowfn: NowFn = utcnow) -> AuthToken:
    """Decodes the Auth Token.

    Args:
        token (str): Auth Token
        nowfn (NowFn, optional): Function to get the current time. Defaults to utcnow.

    Returns:
        AuthToken: Auth Token

    Raises:
        jwt.exceptions.PyJWTError when token is not valid
    """
    exc: PyJWTError | TimeException | None = None

    for secret in config.auth.secret_keys:
        try:
            tok = AuthToken(
                **jwt.decode(
                    token,
                    secret.key,
                    algorithms=[secret.algorithm],
                    options={
                        "verify_exp": False,
                        "verify_nbf": False,
                    },
                )
            )

            # Custom timestamp verification according to the nowfn
            now = nowfn().timestamp()
            nbf = getattr(tok, "nbf", None)
            if nbf is not None and now < nbf:
                raise TimeException(detail="Token not valid yet", user_id=tok.sub)

            exp = getattr(tok, "exp", None)
            if exp is not None and now > exp:
                raise TimeException(detail="Token expired", user_id=tok.sub)

            return tok

        except (TimeException, PyJWTError) as e:
            exc = e
            continue

    if exc is not None:
        raise exc

    # Unclear why we would get here
    raise ValueError("invalid token")


def generate_auth_link(
    user_id: int,
    redirect: str = "/",
    expiry: int = 600,
    nowfn: NowFn = utcnow,
    is_study: bool = False,
) -> str:
    """Generates the link to log in.

    Args:
        user_id (int): User ID
        redirect (str, optional): Redirect URL. Defaults to "/".

    Returns:
        str: Auth Link
    """
    tok = encode_auth_token(str(user_id), expiry=expiry, nowfn=nowfn)
    if is_study:
        return config.study_url(f"/api/study/auth?token={tok}&redirect={redirect}")
    else:
        return config.url(f"/api/v1/auth?token={tok}&redirect={redirect}")


def redirect_with_session(
    destination: str, user_id: int, expiry: int = 86_400 * 30, nowfn: NowFn = utcnow
):
    """Redirect to the destination with a session token."""
    session_token = encode_session_token(user_id, expiry=expiry, nowfn=nowfn)
    response = RedirectResponse(
        config.url(destination) if destination.startswith("/") else destination,
        status_code=303,
    )
    response.set_cookie(
        key="session",
        value=session_token,
        max_age=expiry,
    )
    return response


def redirect_with_session_study(
    destination: str, user_id: str, expiry: int = 86_400 * 30, nowfn: NowFn = utcnow
):
    """Redirect to the destination with a session token."""
    session_token = encode_auth_token(user_id, expiry=expiry, nowfn=nowfn)
    response = RedirectResponse(
        config.study_url(destination) if destination.startswith("/") else destination,
        status_code=303,
    )
    response.set_cookie(
        key="study_session",
        value=session_token,
        max_age=expiry,
    )
    return response


def _wildcard_match(pattern: str, value: str) -> bool:
    """Wildcard match a pattern against a value.

    Example:
    >>> wildcard_match("*.example.com", "foo.example.com")
    True
    >>> wildcard_match("*.example.com", "foo.bar.example.com")
    True
    >>> wildcard_match("*.example.com", "example.com")
    False

    Args:
        pattern (str): The pattern to match.
        value (str): The value to match against.

    Returns:
        bool: True if the value matches the pattern, False otherwise.
    """
    pattern = "^" + re.escape(pattern).replace(r"\*", r".+") + "$"
    return re.match(pattern, value) is not None


def authn_method_for_email(methods: list[AuthnSettings], email: str) -> AuthnSettings:
    """Get the authn method for the given email domain.

    Args:
        methods (list[AuthnSettings]): The list of authn methods (from the config, usually)
        email (str): The email address.

    Returns:
        AuthnSettings: The first authn method that matches
    """
    domain = email.split("@")[1]
    for method in methods:
        # Check if the domain matches any of the domains patterns and is not
        # excluded by any of the excluded_domains patterns
        if any(_wildcard_match(d, domain) for d in method.domains) and not any(
            _wildcard_match(d, domain) for d in method.excluded_domains
        ):
            return method
    raise ValueError(f"No authn method found for domain {domain}")
