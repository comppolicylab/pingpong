import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MoveLectureSlideQuestionsToSlideEndsResult:
    updated: int = 0
    skipped: int = 0
    skipped_question_ids: tuple[int, ...] = ()


def _nearest_slide_page(
    question: models.LectureSlideQuestion,
    pages: Sequence[models.LectureSlidePage],
) -> models.LectureSlidePage | None:
    timed_pages = [
        page
        for page in pages
        if page.start_offset_ms is not None and page.end_offset_ms is not None
    ]
    for page in timed_pages:
        assert page.start_offset_ms is not None
        assert page.end_offset_ms is not None
        # Boundaries belong to the earlier slide so questions already at the end
        # of page N are not migrated to page N+1.
        if page.start_offset_ms <= question.stop_offset_ms <= page.end_offset_ms:
            return page

    page_by_position = {page.position: page for page in pages}
    positioned_page = page_by_position.get(question.slide_position)
    if (
        positioned_page is not None
        and positioned_page.start_offset_ms is not None
        and positioned_page.end_offset_ms is not None
    ):
        return positioned_page

    def distance_to_question(page: models.LectureSlidePage) -> int:
        assert page.start_offset_ms is not None
        assert page.end_offset_ms is not None
        return min(
            abs(question.stop_offset_ms - page.start_offset_ms),
            abs(question.stop_offset_ms - page.end_offset_ms),
        )

    return (
        min(timed_pages, key=distance_to_question) if timed_pages else positioned_page
    )


async def move_lecture_slide_questions_to_slide_ends(
    session: AsyncSession,
) -> MoveLectureSlideQuestionsToSlideEndsResult:
    questions = (
        (
            await session.scalars(
                select(models.LectureSlideQuestion)
                .options(
                    selectinload(models.LectureSlideQuestion.options),
                    selectinload(
                        models.LectureSlideQuestion.lecture_slide_deck
                    ).selectinload(models.LectureSlideDeck.pages),
                )
                .order_by(models.LectureSlideQuestion.id.asc())
            )
        )
        .unique()
        .all()
    )

    updated = 0
    skipped = 0
    skipped_question_ids: list[int] = []
    for question in questions:
        deck = question.lecture_slide_deck
        page = _nearest_slide_page(
            question, sorted(deck.pages, key=lambda item: item.position)
        )
        if page is None or page.start_offset_ms is None or page.end_offset_ms is None:
            skipped += 1
            if question.id is not None:
                skipped_question_ids.append(question.id)
            logger.warning(
                "Skipping lecture slide question without usable slide timing. "
                "question_id=%s deck_id=%s slide_position=%s",
                question.id,
                question.lecture_slide_deck_id,
                question.slide_position,
            )
            continue

        slide_offset_ms = max(page.end_offset_ms - page.start_offset_ms, 0)
        stop_offset_ms = page.end_offset_ms
        changed = (
            question.slide_position != page.position
            or question.slide_offset_ms != slide_offset_ms
            or question.stop_offset_ms != stop_offset_ms
        )
        question.slide_position = page.position
        question.slide_offset_ms = slide_offset_ms
        question.stop_offset_ms = stop_offset_ms

        for option in question.options:
            option_changed = (
                option.continue_slide_position != page.position
                or option.continue_slide_offset_ms != slide_offset_ms
                or option.continue_offset_ms != stop_offset_ms
            )
            option.continue_slide_position = page.position
            option.continue_slide_offset_ms = slide_offset_ms
            option.continue_offset_ms = stop_offset_ms
            changed = changed or option_changed

        if changed:
            updated += 1

    logger.info(
        "Moved lecture slide questions to slide ends. updated=%s skipped=%s "
        "skipped_question_ids=%s",
        updated,
        skipped,
        skipped_question_ids,
    )
    return MoveLectureSlideQuestionsToSlideEndsResult(
        updated=updated,
        skipped=skipped,
        skipped_question_ids=tuple(skipped_question_ids),
    )
