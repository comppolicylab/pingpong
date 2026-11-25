from fastapi import HTTPException


class OpenAccessError(HTTPException):
    def __init__(self, status_code: int, error_code: str, message: str):
        super().__init__(
            status_code, detail={"message": message, "error_code": error_code}
        )


def token_invalid() -> OpenAccessError:
    return OpenAccessError(401, "open_access_token_invalid", "Your session expired.")


def session_displaced() -> OpenAccessError:
    return OpenAccessError(409, "session_displaced", "Continued elsewhere.")


def unavailable() -> OpenAccessError:
    return OpenAccessError(
        503, "open_access_unavailable", "Open Access is temporarily unavailable."
    )
