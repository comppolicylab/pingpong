from pyairtable.orm import Model, fields as F

class ClassAirtableRequest(Model):
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
        table_name = None
        base_id = None
        api_key = None

def create_request_model(base_id: str, table_name: str, api_key: str):
    request_meta = type(
        "Meta",
        (),
        {"base_id": base_id, "table_name": table_name, "api_key": api_key}
    )
    ClassAirtableRequest.Meta = request_meta
    return ClassAirtableRequest