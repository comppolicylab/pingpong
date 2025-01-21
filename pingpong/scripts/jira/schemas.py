from pyairtable.orm import Model, fields as F
from pydantic import BaseModel

from pingpong.scripts.airtable.vars import (
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
    start_date = F.TextField("Start Date (String)")
    end_date = F.TextField("End Date (String)")
    student_count = F.NumberField("Student Count")
    randomization = F.TextField("Randomization Result (Text)")
    pingpong_class_id = F.LookupField[int]("PingPong ID (from PingPong Class Record)")
    student_survey_url = F.UrlField("Student Survey Link")
    jira = F.CheckboxField("Added to Jira")
    jira_account_id = F.TextField("Jira ProductId")
    jira_entitlement = F.TextField("Jira EntitlementId")
    jira_added_entitlement = F.CheckboxField("Added Entitlement")
    jira_added_ent_fields = F.CheckboxField("Added Entitlement Fields")
    jira_instructor_id = F.LookupField[str]("Instructor Jira ID")
    airtable_url = F.TextField("Airtable Record URL")

    class Meta:
        table_name: str = "Airtable Classes"
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class Instructor(Model):
    first_name = F.TextField("First Name")
    last_name = F.TextField("Last Name")
    email = F.EmailField("Email")
    classes = F.LinkField("Classes", AirtableClass)
    deadline_url = F.UrlField("Deadline Survey URL")
    jira = F.CheckboxField("Added to Jira")
    jira_account_id = F.TextField("Jira AccountId")
    jira_project = F.CheckboxField("Added to Jira Project")
    jira_fields = F.CheckboxField("Added Jira Fields")
    airtable_url = F.TextField("Airtable Record URL")

    class Meta:
        table_name: str = "Instructors"
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class AddInstructorRequest(BaseModel):
    email: str
    displayName: str


class JiraCustomerResponse(BaseModel):
    accountId: str
