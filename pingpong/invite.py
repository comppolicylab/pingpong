from .email import EmailSender
from .schemas import CreateInvite


async def send_invite(
    sender: EmailSender, invite: CreateInvite, link: str, silent: bool = False
):
    """Send an email invitation for a user to join a class."""
    subject = f"You've been invited to join {invite.class_name}!"
    message = f"""\
Hello! You've been invited to join {invite.class_name} on PingPong. \
To join, click the link below:

{link}\
"""

    if silent:
        print(f"Would have sent email to {invite.email} with subject {subject}")
        print(message)
        return
    await sender.send(invite.email, subject, message)
