from starlette.requests import HTTPConnection

MARKER_HEADER = "X-PingPong-OA"
MARKER_QUERY_PARAM = "pp_oa"
ACCESS_TOKEN_HEADER = "X-PingPong-OA-Token"
ACCESS_TOKEN_COOKIE = "pp_oa_token"


def has_marker(connection: HTTPConnection) -> bool:
    return (
        connection.headers.get(MARKER_HEADER) == "1"
        or connection.query_params.get(MARKER_QUERY_PARAM) == "1"
    )


def access_token(connection: HTTPConnection, *, allow_cookie: bool) -> str | None:
    return connection.headers.get(ACCESS_TOKEN_HEADER) or (
        connection.cookies.get(ACCESS_TOKEN_COOKIE)
        if allow_cookie and has_marker(connection)
        else None
    )


def access_token_cookie_path(class_id: int, thread_id: int) -> str:
    return f"/api/v1/class/{class_id}/thread/{thread_id}/"
