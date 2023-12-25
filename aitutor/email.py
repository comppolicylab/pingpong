import asyncio
from abc import abstractmethod
from typing import Protocol

from azure.communication.email import EmailClient

from .config import config
from .schemas import CreateInvite


class EmailSender(Protocol):
    @abstractmethod
    async def send(self, to: str, subject: str, message: str):
        ...


class AzureEmailSender(EmailSender):
    def __init__(self, from_address: str, conn_str: str):
        self.client = EmailClient.from_connection_string(conn_str)
        self.from_address = from_address

    async def send(self, to: str, subject: str, message: str):
        azure_msg = {
            "senderAddress": self.from_address,
            "recipients": {
                "to": [{"address": to}],
            },
            "content": {
                "subject": subject,
                "plainText": message,
            },
        }
        poller = self.client.begin_send(azure_msg)

        # Create a future for the polling loop
        send_future = asyncio.get_running_loop().create_future()
        poller.add_done_callback(send_future.set_result)

        # Wait for the send operation to complete
        await send_future
        result = poller.result()
        if result["error"]:
            raise Exception('Failed to send email: {result["error"]}')


def get_default_sender() -> EmailSender:
    """Get the default email send client based on config."""
    return AzureEmailSender(config.email.from_address, config.email.connection_string)


async def send_invite(sender: EmailSender, invite: CreateInvite):
    """Send an email invitation for a user to join a class."""
    subject = f"You've been invited to join {invite.class_name}!"
    message = f"""
    Hello! You've been invited to join {invite.class_name} on AI Tutor. \
            To join, click the link below:

    {config.url("/login")}
    """
    await sender.send(invite.email, subject, message)
