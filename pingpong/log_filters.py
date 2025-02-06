import logging


class IgnoreHealthEndpoint(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """Return whether the record should be logged.

        True means log, False means discard.
        """
        return '"GET /health HTTP/1.1" 200' not in record.getMessage()
