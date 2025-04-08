import json
import pingpong.scripts.qualtrics.schemas as scripts_schemas
from pingpong.scripts.qualtrics.vars import (
    QUALTRICS_API_KEY,
)


async def get_exam_object(session, url: str) -> scripts_schemas.ExamJSON:
    async with session.get(
        url,
        raise_for_status=True,
        headers={
            "Accept": "application/json",
        },
    ) as resp:
        response = await resp.json()
        return scripts_schemas.ExamJSON(**response)


async def import_qsf(session, qsf: str) -> scripts_schemas.QualtricsAddSurveyResponse:
    try:
        json.loads(qsf)
    except json.JSONDecodeError as e:
        # Extract position of the error
        error_pos = e.pos

        # Split the string into lines
        lines = qsf.splitlines()  # Changed from json_string to qsf

        # Calculate line number and character position within that line
        current_pos = 0
        for line_number, line in enumerate(lines):
            next_pos = current_pos + len(line) + 1  # +1 for the newline character
            if current_pos <= error_pos < next_pos:
                raise ValueError(f"Offending line {line_number + 1}: {line.strip()}")
            current_pos = next_pos

    async with session.post(
        "https://pdx1.qualtrics.com/API/v3/survey-definitions",
        raise_for_status=True,
        headers={
            "X-API-TOKEN": QUALTRICS_API_KEY,
            "Content-Type": "application/json",
        },
        json=json.loads(qsf),
    ) as resp:
        response = await resp.json()
        return scripts_schemas.QualtricsAddSurveyResponse(**response)


async def publish_survey(session, survey_id: str) -> bool:
    async with session.post(
        f"https://pdx1.qualtrics.com/API/v3/survey-definitions/{survey_id}/versions",
        raise_for_status=True,
        headers={
            "X-API-TOKEN": QUALTRICS_API_KEY,
            "Content-Type": "application/json",
        },
        json={"Published": True, "Description": "Initial version"},
    ) as resp:
        response = await resp.json()
        return response["result"]["metadata"]["wasPublished"]
