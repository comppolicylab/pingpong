import pingpong.models as models
import pingpong.schemas as schemas
from sqlalchemy.ext.asyncio import AsyncSession

from .lecture_slide_service import lecture_slide_summary_from_model
from .lecture_video_service import lecture_video_summary_from_model

_ASSISTANT_RESPONSE_FIELDS_EXCLUDED_FROM_MODEL = frozenset(
    {"avatar_url", "lecture_video", "lecture_slide_deck", "share_links", "endorsed"}
)


async def assistant_response_from_model(
    session: AsyncSession, asst: models.Assistant
) -> schemas.Assistant:
    data = {
        field_name: getattr(asst, field_name)
        for field_name in schemas.Assistant.model_fields
        if field_name not in _ASSISTANT_RESPONSE_FIELDS_EXCLUDED_FROM_MODEL
    }
    data["lecture_video"] = await lecture_video_summary_from_model(
        session, asst.lecture_video
    )
    data["lecture_slide_deck"] = await lecture_slide_summary_from_model(
        asst.lecture_slide_deck
    )
    data["avatar_url"] = (
        f"/api/v1/class/{asst.class_id}/assistant/{asst.id}/avatar"
        f"?v={asst.avatar_file_id}"
        if asst.avatar_file_id is not None
        else None
    )
    return schemas.Assistant.model_validate(data)
