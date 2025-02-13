import logging
import re


class IgnoreHealthEndpoint(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """Return whether the record should be logged.

        True means log, False means discard.
        """
        return not bool(re.search(r'"GET /health.*" 200', record.getMessage()))
