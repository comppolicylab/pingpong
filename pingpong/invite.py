from .email import EmailSender
from .schemas import CreateInvite
from .template import email_template as message_template
from .time import convert_seconds


async def send_invite(
    sender: EmailSender,
    invite: CreateInvite,
    link: str,
    expires: int = 86400,
    silent: bool = False,
):
    """Send an email invitation for a user to join a class."""
    subject = f"You're invited to join {invite.class_name}!"

    message = message_template.substitute(
        {
            "title": f"You&#8217;re invited to join {invite.class_name} on PingPong.",
            "subtitle": (
                f"{invite.inviter_name} has invited you"
                if invite.inviter_name
                else "You have been invited"
            )
            + " to join "
            + invite.class_name
            + (f" as {invite.formatted_role}" if invite.formatted_role else "")
            + " on PingPong. Click the link below to accept "
            + ("their" if invite.formatted_role else "this")
            + " invitation.",
            "type": "invitation",
            "cta": f"Join {invite.class_name} on PingPong",
            "underline": "PingPong is a tool for using large language models in a group setting. It&#8217;s built on top of GPT-4, a large language model developed by OpenAI.",
            "expires": convert_seconds(expires),
            "link": link,
            "email": invite.email,
            "legal_text": "because a PingPong user invited you to join their Group",
        }
    )

    if silent:
        print(f"Would have sent email to {invite.email} with subject {subject}")
        print(message)
        return
    await sender.send(invite.email, subject, message)
