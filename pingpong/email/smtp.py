import ssl
from email.message import EmailMessage

import aiosmtplib

from .base import EmailSender


class SmtpEmailSender(EmailSender):
    def __init__(
        self,
        from_address: str,
        *,
        host: str,
        port: int = 25,
        user: str | None = None,
        pw: str | None = None,
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

        # If message is a string, treat it as HTML content
        if isinstance(message, str):
            msg.add_alternative(message, subtype="html")
        elif isinstance(message, EmailMessage):
            msg = message
        else:
            raise ValueError("Message must be either a string or EmailMessage object.")

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
