from abc import ABC, abstractmethod

import aiohttp
from discord import Webhook

from .schemas import SupportRequest


class BaseSupportDriver(ABC):
    @abstractmethod
    async def post(self, req: SupportRequest, **kwargs):
        ...


class DiscordSupportDriver(BaseSupportDriver):
    def __init__(self, webhook: str):
        self.webhook = webhook

    async def post(self, req: SupportRequest, **kwargs):
        async with aiohttp.ClientSession() as session:
            webhook = Webhook.from_url(self.webhook, session=session)
            msg = "**Support request from the app**\n"
            if req.name:
                msg += f"**Name:** {req.name}\n"
            if req.email:
                msg += f"**Email:** {req.email}\n"
            if req.category:
                msg += f"**Category:** {req.category}\n"
            for key, value in kwargs.items():
                msg += f"**{key}:** {value}\n"

            msg += "\n====================\n"
            msg += req.message

            await webhook.send(msg)
