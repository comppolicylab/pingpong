import os


class Stream:
    """Wrapper around os pipe to create a stream."""

    def __init__(self):
        self._pr, self._pw = os.pipe()
        self._reader = os.fdopen(self._pr, "r")
        self._writer = os.fdopen(self._pw, "w")

    @property
    def reader(self):
        return self._reader

    @property
    def writer(self):
        return self._writer

    def __enter__(self):
        return self._reader, self._writer

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self._writer.flush()
        self._writer.close()
        self._reader.close()
