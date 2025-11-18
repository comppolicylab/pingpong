import aiohttp
import logging

from pyairtable.formulas import match

from pingpong.scripts.qualtrics import schemas as scripts_schemas
from pingpong.scripts.qualtrics import server_requests
from pingpong.scripts.qualtrics.vars import QUALTRICS_BASE_URL
from pingpong.scripts.qualtrics.exam_qsf_template import generate_qsf
from pingpong.scripts.qualtrics.webdriver import QualtricsWebDriver


logger = logging.getLogger(__name__)

if not QUALTRICS_BASE_URL:
    raise ValueError("Missing Qualtrics credentials in environment.")
else:
    _QUALTRICS_BASE_URL = QUALTRICS_BASE_URL


async def process_exams(email: str) -> None:
    classes_to_create_exam = scripts_schemas.AirtableClass.all(
        formula=(match({"Postassessment": "JSON Added"}))
    )
    if not classes_to_create_exam:
        logger.info("No classes to create exams for.")
        return

    webdriver = QualtricsWebDriver(email)
    webdriver.login()

    async with aiohttp.ClientSession() as session:
        for class_ in classes_to_create_exam:
            if len(class_.json_file) != 1:
                logger.warning(f"Class {class_.name} does not have a valid JSON file.")
                continue
            try:
                exam = await server_requests.get_exam_object(
                    session, class_.json_file[0]["url"]
                )
                assert exam.pp_airtable_class_RID == class_.id
                qualtrics_file = generate_qsf(exam, class_)
                result = await server_requests.import_qsf(session, qualtrics_file)
                logger.info(f"Exam imported for class: {class_.name}")
                assert await server_requests.publish_survey(
                    session, result.result.SurveyID
                )
                logger.info(f"Exam published for class: {class_.name}")
                webdriver.enable_survey_workflow(result.result.SurveyID)
                logger.info(f"Survey workflow enabled for class: {class_.name}")
                webdriver.enable_response_collection(result.result.SurveyID)
                logger.info(f"Response collection enabled for class: {class_.name}")
                class_.postassessment_status = "Created"
                class_.postassessment_url = (
                    f"{_QUALTRICS_BASE_URL}/jfe/form/{result.result.SurveyID}"
                )
                class_.postassessment_workflow = True
                class_.save()
                logger.info(
                    f"Class {class_.name} postassessment URL: {class_.postassessment_url}"
                )
            except Exception as e:
                class_.postassessment_status = "Script Error"
                class_.postassessment_error = str(e)
                class_.save()
                logger.warning(
                    f"Error processing class {class_.name} {class_.id}: {e}",
                    exc_info=True,
                )
                continue
