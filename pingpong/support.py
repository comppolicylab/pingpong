from abc import ABC, abstractmethod
from typing import Union, Literal
from functools import cached_property

from pydantic_settings import BaseSettings
import aiohttp
from discord import Webhook

from .schemas import SupportRequest


class BaseSupportDriver(ABC):
    @abstractmethod
    async def post(self, req: SupportRequest, **kwargs):
        raise NotImplementedError


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


class DiscordSettings(BaseSettings):
    """Settings for getting help with Discord."""

    type: Literal["discord"] = "discord"
    webhook: str
    invite: str
    template: str = (
        'We run a <a href="{invite}" class="underline" '
        'rel="noopener noreferrer" target="_blank">'
        "Discord server</a> where you can get help with PingPong."
    )

    def blurb(self) -> str:
        return self.template.format(invite=self.invite)

    @cached_property
    def driver(self) -> DiscordSupportDriver:
        return DiscordSupportDriver(self.webhook)


class NoSupportSettings(BaseSettings):
    type: Literal["none"] = "none"
    placeholder: str = (
        "We sadly cannot offer additional support for this app right now."
    )

    def blurb(self) -> str:
        return self.placeholder

    @cached_property
    def driver(self) -> None:
        return None


class CustomTextSettings(BaseSettings):
    type: Literal["text"] = "text"
    text: str

    def blurb(self) -> str:
        return self.text

    @cached_property
    def driver(self) -> None:
        return None


SupportSettings = Union[DiscordSettings, NoSupportSettings, CustomTextSettings]
