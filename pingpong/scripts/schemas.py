from pyairtable.orm import Model, fields as F

from pingpong.scripts.vars import (
    AIRTABLE_API_KEY,
    AIRTABLE_BASE_ID,
    AIRTABLE_TABLE_NAME,
)

if not AIRTABLE_BASE_ID or not AIRTABLE_API_KEY or not AIRTABLE_TABLE_NAME:
    raise ValueError("Missing Airtable credentials in environment.")
else:
    _AIRTABLE_BASE_ID = AIRTABLE_BASE_ID
    _AIRTABLE_API_KEY = AIRTABLE_API_KEY
    _AIRTABLE_TABLE_NAME = AIRTABLE_TABLE_NAME


class AirtableClassRequest(Model):
    status = F.SelectField("Status")
    status_notes = F.TextField("Status Notes")
    class_name = F.TextField("Class Name")
    class_term = F.TextField("Class Term")
    class_institution = F.TextField("Class Institution")
    teacher_email = F.EmailField("Teacher Email")
    billing_provider = F.SelectField("Billing Provider")
    billing_api_key = F.TextField("Billing API Selection")
    assistant_name = F.TextField("Assistant Name")
    assistant_model = F.TextField("Assistant Model")
    assistant_description = F.TextField("Assistant Description")
    assistant_instructions = F.TextField("Assistant Instructions")
    hide_prompt = F.CheckboxField("Hide Prompt")
    use_latex = F.CheckboxField("Use LaTeX")
    file_search = F.CheckboxField("Enable File Search")
    code_interpreter = F.CheckboxField("Enable Code Interpreter")
    publish = F.CheckboxField("Publish")

    class Meta:
        table_name: str = _AIRTABLE_TABLE_NAME
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY
