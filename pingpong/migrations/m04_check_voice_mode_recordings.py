import io
import logging
import csv
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
from pingpong.config import config


logger = logging.getLogger(__name__)


async def _is_recording_available(recording_id: str) -> bool:
    """Return True if the recording can be fetched from the current audio store.

    Attempts to start streaming the file and closes the generator immediately
    to avoid leaking resources.
    """
    try:
        agen = config.audio_store.store.get_file(recording_id)
        async for _ in agen:
            # We could stream the entire file, but for an existence check, a
            # single successful chunk is sufficient.
            break
        # Ensure the generator is closed to release resources
        try:
            await agen.aclose()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def check_voice_mode_recordings(session: AsyncSession) -> None:
    """Iterate through VoiceModeRecording rows and print missing ones.

    For each VoiceModeRecording, attempts to fetch from the configured
    audio store. Logs any recordings that are not available.
    """
    missing = 0
    total = 0

    # Prepare CSV export buffer and header
    csv_buffer = io.StringIO()
    csvwriter = csv.writer(csv_buffer)
    header = [
        "Recording ID",
        "Recording File",
        "Created At",
        "Group Name",
        "Thread ID",
        "Thread URL",
        "Thread User IDs",
        "Thread User Names",
        "Thread User Emails",
        "Moderator Names",
        "Moderator Emails",
    ]
    csvwriter.writerow(header)

    # Cache moderators per class to avoid repeated lookups
    moderator_cache: dict[int, tuple[str, str]] = {}

    async def get_moderators(class_id: int) -> tuple[str, str]:
        if class_id in moderator_cache:
            return moderator_cache[class_id]
        names: list[str] = []
        emails: list[str] = []
        try:
            # Initialize and query authz for teachers (moderators)
            await config.authz.driver.init()
            async with config.authz.driver.get_client() as c:
                moderator_ids = await c.list_entities(
                    target=f"class:{class_id}", relation="teacher", type_="user"
                )
        except Exception:
            moderator_ids = []
        if moderator_ids:
            users = await models.User.get_all_by_id(session, moderator_ids)
            for u in users:
                name = u.display_name or (
                    f"{u.first_name or ''} {u.last_name or ''}".strip() or None
                )
                names.append(name or "")
                emails.append(u.email or "")
        result = (", ".join(names), ", ".join(emails))
        moderator_cache[class_id] = result
        return result

    async def build_csv_row(recording: models.VoiceModeRecording) -> list[str]:
        """Build a CSV row for a missing or unavailable recording."""
        class_id = recording.thread.class_id if recording.thread else None
        thread_id = recording.thread_id
        thread_url = (
            config.url(f"/group/{class_id}/thread/{thread_id}")
            if class_id and thread_id
            else ""
        )
        course_name = (
            recording.thread.class_.name
            if recording.thread and recording.thread.class_
            else ""
        )
        # Thread users
        t_users = recording.thread.users if recording.thread else []
        user_ids = ", ".join(str(u.id) for u in t_users)
        user_names = ", ".join(
            (
                u.display_name
                or f"{u.first_name or ''} {u.last_name or ''}".strip()
                or ""
            )
            for u in t_users
        )
        user_emails = ", ".join((u.email or "") for u in t_users)
        mod_names = mod_emails = ""
        if class_id:
            mod_names, mod_emails = await get_moderators(int(class_id))

        return [
            recording.id,
            recording.recording_id or "",
            (
                recording.created_at.astimezone(timezone.utc).isoformat()
                if recording.created_at
                else ""
            ),
            course_name,
            thread_id or "",
            thread_url,
            user_ids,
            user_names,
            user_emails,
            mod_names,
            mod_emails,
        ]

    async for recording in models.VoiceModeRecording.get_all_gen(session):
        total += 1
        rid = recording.recording_id
        if not rid:
            missing += 1
            logger.info(
                "Missing (no recording_id): VoiceModeRecording id=%s thread_id=%s",
                recording.id,
                getattr(recording, "thread_id", None),
            )
            csvwriter.writerow(await build_csv_row(recording))
            continue

        available = await _is_recording_available(rid)
        if not available:
            missing += 1
            logger.info(
                "Not available in audio store: VoiceModeRecording id=%s recording_id=%s thread_id=%s class=%s",
                recording.id,
                rid,
                recording.thread_id,
                recording.thread.class_.name,
            )
            csvwriter.writerow(await build_csv_row(recording))

    logger.info(
        "Checked %s VoiceModeRecording rows. Missing/unavailable: %s",
        total,
        missing,
    )

    # Save CSV to the local exports store
    csv_buffer.seek(0)
    filename = f"missing_voice_mode_recordings_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}.csv"
    await config.artifact_store.store.put(
        filename, csv_buffer, "text/csv;charset=utf-8"
    )
    csv_buffer.close()
    logger.info("Saved report to local exports: %s", filename)
