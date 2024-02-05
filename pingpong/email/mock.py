import logging
from typing import NamedTuple

from .base import EmailSender

logger = logging.getLogger(__name__)


MockEmail = NamedTuple("MockEmail", [("to", str), ("subject", str), ("body", str)])


class MockEmailSender(EmailSender):
    def __init__(self):
        self.sent: list[MockEmail] = []

    async def send(self, to: str, subject: str, body: str):
        self.sent.append(MockEmail(to, subject, body))
        logger.info(f"Mock email sent to {to} with subject {subject} and body {body}")
