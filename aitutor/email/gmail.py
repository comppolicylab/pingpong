from .smtp import SmtpEmailSender


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
