from .email import EmailSender
from .schemas import (
    ClassSummaryExport,
    ClonedGroupNotification,
    CreateInvite,
    DownloadExport,
)
from .template import email_template as message_template
from .template import summary_template
from .time import convert_seconds


async def send_invite(
    sender: EmailSender,
    invite: CreateInvite,
    link: str,
    expires: int = 86400,
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
            "underline": "PingPong is a tool for using large language models in a group setting. It&#8217;s built on top of models developed by OpenAI.",
            "expires": convert_seconds(expires),
            "link": link,
            "email": invite.email,
            "legal_text": "because a PingPong user invited you to join their Group",
        }
    )

    await sender.send(invite.email, subject, message)


async def send_export_download(
    sender: EmailSender,
    invite: DownloadExport,
    expires: int = 43200,
):
    subject = f"Your data export is ready for {invite.class_name}"

    message = message_template.substitute(
        {
            "title": "Your data export is ready.",
            "subtitle": "We have successfully exported the thread data you requested from "
            + invite.class_name
            + ". You can download your data export below in a CSV format. Please note that user ids are anonymized, but consistent across threads and exports.",
            "type": "download link",
            "cta": "Download your data export",
            "underline": "If your download link has expired, you can create a new export from the Manage Group page on PingPong. All exports are deleted after they expire.",
            "expires": convert_seconds(expires),
            "link": invite.link,
            "email": invite.email,
            "legal_text": "because you requested a data export from PingPong",
        }
    )

    await sender.send(invite.email, subject, message)


async def send_clone_group_notification(
    sender: EmailSender,
    invite: ClonedGroupNotification,
    expires: int = 86400,
):
    subject = f"Your new {invite.class_name} group is ready!"

    message = message_template.substitute(
        {
            "title": "Your new cloned group is ready.",
            "subtitle": "We have successfully copied over configuration settings, assistants and users from the original group as you requested. You can now start using your new group. Use the link below to access it.",
            "type": "link",
            "cta": "Go to your new group",
            "underline": "PingPong is a tool for using large language models in a group setting. It&#8217;s built on top of models developed by OpenAI.",
            "link": invite.link,
            "email": invite.email,
            "expires": convert_seconds(expires),
            "legal_text": "because you requested for a new group to be created on PingPong",
        }
    )
    await sender.send(invite.email, subject, message)


async def send_summary(
    sender: EmailSender,
    invite: ClassSummaryExport,
):
    subject = (
        f"Your {invite.summary_type or 'activity summary'} for {invite.class_name}"
    )

    message = summary_template.substitute(
        {
            "name": invite.first_name,
            "courseName": invite.class_name,
            "summary": invite.summary_html,
            "link": invite.link,
            "title": invite.title or "Your group's activity summary is here.",
            "time": invite.time_since,
            "legal_text": f"you are a Moderator in {invite.class_name}. You can change your notification settings on the Manage Group page on PingPong",
        }
    )

    await sender.send(invite.email, subject, message)
