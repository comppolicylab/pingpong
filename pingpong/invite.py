from .email import EmailSender
from .schemas import CreateInvite
from .template import email_template as messageTemplate


async def send_invite(
    sender: EmailSender, invite: CreateInvite, link: str, silent: bool = False
):
    """Send an email invitation for a user to join a class."""
    subject = f"You're invited to join {invite.class_name}!"

    message = messageTemplate.substitute(
        {
            "inviterNameString": f"{invite.inviter_name} has invited you"
            if invite.inviter_name
            else "You have been invited",
            "class": invite.class_name,
            "roleString": f" as {invite.formatted_role}"
            if invite.formatted_role
            else "",
            "inviteArticleString": "their" if invite.formatted_role else "this",
            "link": link,
            "email": invite.email,
        }
    )

    if silent:
        print(f"Would have sent email to {invite.email} with subject {subject}")
        print(message)
        return
    await sender.send(invite.email, subject, message)
