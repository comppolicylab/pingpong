import pingpong.models as models
import pingpong.schemas as schemas
from sqlalchemy.ext.asyncio import AsyncSession

from .lecture_video_service import lecture_video_summary_from_model


async def assistant_response_from_model(
    session: AsyncSession, asst: models.Assistant
) -> schemas.Assistant:
    data = {
        field_name: getattr(asst, field_name)
        for field_name in schemas.Assistant.model_fields
        if field_name not in {"lecture_video", "share_links", "endorsed"}
    }
    data["lecture_video"] = await lecture_video_summary_from_model(
        session, asst.lecture_video
    )
    return schemas.Assistant.model_validate(data)
