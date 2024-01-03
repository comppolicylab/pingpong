import asyncio
import ssl
from abc import abstractmethod
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
from azure.communication.email import EmailClient

from .schemas import CreateInvite


class EmailSender(Protocol):
    @abstractmethod
    async def send(self, to: str, subject: str, message: str):
        ...


class SmtpEmailSender(EmailSender):
    def __init__(
        self,
        from_address: str,
        *,
        user: str,
        pw: str,
        host: str,
        port: int,
        use_tls: bool = False,
        start_tls: bool = False,
        use_ssl: bool = False,
    ):
        self.from_address = from_address
        self.user = user
        self.pw = pw
        self.host = host
        self.port = port
        self.use_tls = use_tls
        self.start_tls = start_tls
        self.use_ssl = use_ssl

    async def send(self, to: str, subject: str, message: str):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = to
        msg.set_content(message)

        tls_context: ssl.SSLContext | None = None
        if self.use_ssl:
            tls_context = ssl.create_default_context()

        await aiosmtplib.send(
            msg,
            hostname=self.host,
            port=self.port,
            use_tls=self.use_tls,
            start_tls=self.start_tls,
            username=self.user,
            password=self.pw,
            tls_context=tls_context,
        )


class GmailEmailSender(SmtpEmailSender):
    def __init__(self, from_address: str, pw: str):
        super().__init__(
            from_address,
            user=from_address.split("@")[0],
            pw=pw,
            host="smtp.gmail.com",
            port=465,
            use_tls=True,
            use_ssl=True,
        )


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


async def send_invite(
    sender: EmailSender, invite: CreateInvite, link: str, silent: bool = False
):
    """Send an email invitation for a user to join a class."""
    subject = f"You've been invited to join {invite.class_name}!"
    message = f"""\
Hello! You've been invited to join {invite.class_name} on AI Tutor. \
To join, click the link below:

{link}\
"""

    if silent:
        print(f"Would have sent email to {invite.email} with subject {subject}")
        print(message)
        return
    await sender.send(invite.email, subject, message)
