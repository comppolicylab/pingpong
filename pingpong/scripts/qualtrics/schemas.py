from pyairtable.orm import Model, fields as F
from pydantic import BaseModel

from pingpong.scripts.qualtrics.vars import (
    AIRTABLE_API_KEY,
    AIRTABLE_BASE_ID,
)

if not AIRTABLE_BASE_ID or not AIRTABLE_API_KEY:
    raise ValueError("Missing Airtable credentials in environment.")
else:
    _AIRTABLE_BASE_ID = AIRTABLE_BASE_ID
    _AIRTABLE_API_KEY = AIRTABLE_API_KEY


class AirtableClass(Model):
    name = F.TextField("Name")
    # start_date = F.TextField("Start Date (String)")
    # end_date = F.TextField("End Date (String)")
    # student_count = F.NumberField("Student Count")
    randomization = F.TextField("Randomization Result")
    pingpong_class_id = F.LookupField[int]("PP Group ID")
    # student_survey_url = F.UrlField("Student Survey Link")
    # jira = F.CheckboxField("Added to Jira")
    # jira_account_id = F.TextField("Jira ProductId")
    # jira_entitlement = F.TextField("Jira EntitlementId")
    # jira_added_entitlement = F.CheckboxField("Added Entitlement")
    # jira_added_ent_fields = F.CheckboxField("Added Entitlement Fields")
    # jira_instructor_id = F.LookupField[str]("Instructor Jira ID")
    # airtable_url = F.TextField("Airtable Record URL")
    json_file = F.AttachmentsField("Exam JSON")
    postassessment_status = F.SelectField("PostAssessment")
    postassessment_error = F.TextField("PostAssessment Generation Error")
    postassessment_url = F.UrlField("PostAssessment Link")
    postassessment_workflow = F.CheckboxField("Workflow On?")

    class Meta:
        table_name: str = "📗 Classes"
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class ExamQuestion(BaseModel):
    question: str
    options: list[str]
    uses_latex: bool
    answer: str


class ExamJSON(BaseModel):
    pp_airtable_class_RID: str
    uses_latex: bool
    questions: list[ExamQuestion]


class QualtricsAddSurveyResult(BaseModel):
    SurveyID: str


class QualtricsAddSurveyResponse(BaseModel):
    result: QualtricsAddSurveyResult
