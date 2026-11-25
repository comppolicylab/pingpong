from starlette.requests import HTTPConnection

MARKER_HEADER = "X-PingPong-OA"
MARKER_QUERY_PARAM = "pp_oa"
ACCESS_TOKEN_HEADER = "X-PingPong-OA-Token"
ACCESS_TOKEN_QUERY_PARAM = "oa_token"


def has_marker(connection: HTTPConnection) -> bool:
    return (
        connection.headers.get(MARKER_HEADER) == "1"
        or connection.query_params.get(MARKER_QUERY_PARAM) == "1"
    )


def access_token(connection: HTTPConnection, *, allow_query: bool) -> str | None:
    return connection.headers.get(ACCESS_TOKEN_HEADER) or (
        connection.query_params.get(ACCESS_TOKEN_QUERY_PARAM) if allow_query else None
    )
