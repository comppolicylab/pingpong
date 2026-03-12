import pingpong.models as models
import pingpong.schemas as schemas
from sqlalchemy.ext.asyncio import AsyncSession

from .lecture_video_service import lecture_video_summary_from_model

_ASSISTANT_RESPONSE_FIELDS_EXCLUDED_FROM_MODEL = frozenset(
    {"lecture_video", "share_links", "endorsed"}
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
    return schemas.Assistant.model_validate(data)
