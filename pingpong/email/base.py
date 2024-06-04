from abc import abstractmethod
from typing import Protocol


class EmailSender(Protocol):
    @abstractmethod
    async def send(self, to: str, subject: str, message: str): ...
