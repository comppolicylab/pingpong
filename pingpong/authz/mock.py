class MockFgaAuthzServer:
    def __init__(
        self,
        *,
        scheme: str,
        host: str,
        port: int,
        store: str,
        key: str | None = None,
    ):
        self.scheme = scheme
        self.host = host
        self.port = port
        self.store = store
        self.key = key

    def start(self):
        ...
