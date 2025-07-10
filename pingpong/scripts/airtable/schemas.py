from pyairtable.orm import Model, fields as F
from pydantic import BaseModel

from pingpong.scripts.airtable.vars import (
    AIRTABLE_API_KEY,
    AIRTABLE_BASE_ID,
    AIRTABLE_NONSTUDY_BASE_ID,
)

if not AIRTABLE_BASE_ID or not AIRTABLE_NONSTUDY_BASE_ID or not AIRTABLE_API_KEY:
    raise ValueError("Missing Airtable credentials in environment.")
else:
    _AIRTABLE_BASE_ID = AIRTABLE_BASE_ID
    _AIRTABLE_API_KEY = AIRTABLE_API_KEY
    _AIRTABLE_NONSTUDY_BASE_ID = AIRTABLE_NONSTUDY_BASE_ID


class AssistantTemplate(Model):
    version = F.NumberField("Version")
    name = F.TextField("Assistant Name")
    description = F.TextField("Assistant Description")
    model_azure = F.SelectField("Assistant Model (Azure)")
    model_oai = F.SelectField("Assistant Model (OAI)")
    prompt_template = F.LookupField[str]("Main Prompt (from Current Prompt)")
    course_name_code = F.LookupField[str]("Course Name Code (from Current Prompt)")
    prog_lang_sub_code = F.LookupField[str](
        "Prog. Lang. Substitute (from Current Prompt)"
    )
    prog_lang_code_single = F.LookupField[str](
        "Prog. Lang. Code — Single (from Current Prompt)"
    )
    prog_lang_code_multi_and = F.LookupField[str](
        "Prog. Lang. Code — Multi AND (from Current Prompt)"
    )
    prog_lang_code_multi_or = F.LookupField[str](
        "Prog. Lang. Code — Multi OR (from Current Prompt)"
    )
    prog_lang_python = F.LookupField[str](
        "Prog. Lang. Python — Extra (from Current Prompt)"
    )
    prog_lang_any = F.LookupField[str]("Prog. Lang. Any — Extra (from Current Prompt)")
    prog_lang_single_no_python = F.LookupField[str](
        "Prog. Lang. Single — No Python (from Current Prompt)"
    )
    prog_lang_single_with_python = F.LookupField[str](
        "Prog. Lang. Single — With Python (from Current Prompt)"
    )
    prog_lang_multi_no_python = F.LookupField[str](
        "Prog. Lang. Multi — No Python (from Current Prompt)"
    )
    prog_lang_multi_with_python = F.LookupField[str](
        "Prog. Lang. Multi — With Python (from Current Prompt)"
    )
    hide_prompt = F.CheckboxField("Hide Prompt")
    use_latex = F.CheckboxField("Use LaTeX")
    file_search = F.CheckboxField("Enable File Search")
    code_interpreter = F.CheckboxField("Enable Code Interpreter")
    experimental_vision = F.CheckboxField("Experimental Vision")
    temperature = F.NumberField("Temperature")
    publish = F.CheckboxField("Publish")

    class Meta:
        table_name: str = "Assistant Templates"
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class AssistantTemplateNonStudy(Model):
    version = F.NumberField("Version")
    name = F.TextField("Assistant Name")
    description = F.TextField("Assistant Description")
    model_azure = F.SelectField("Assistant Model (Azure)")
    model_oai = F.SelectField("Assistant Model (OAI)")
    prompt_template = F.LookupField[str]("Main Prompt (from Current Prompt)")
    course_name_code = F.LookupField[str]("Course Name Code (from Current Prompt)")
    prog_lang_sub_code = F.LookupField[str](
        "Prog. Lang. Substitute (from Current Prompt)"
    )
    prog_lang_code_single = F.LookupField[str](
        "Prog. Lang. Code — Single (from Current Prompt)"
    )
    prog_lang_code_multi_and = F.LookupField[str](
        "Prog. Lang. Code — Multi AND (from Current Prompt)"
    )
    prog_lang_code_multi_or = F.LookupField[str](
        "Prog. Lang. Code — Multi OR (from Current Prompt)"
    )
    prog_lang_python = F.LookupField[str](
        "Prog. Lang. Python — Extra (from Current Prompt)"
    )
    prog_lang_any = F.LookupField[str]("Prog. Lang. Any — Extra (from Current Prompt)")
    prog_lang_single_no_python = F.LookupField[str](
        "Prog. Lang. Single — No Python (from Current Prompt)"
    )
    prog_lang_single_with_python = F.LookupField[str](
        "Prog. Lang. Single — With Python (from Current Prompt)"
    )
    prog_lang_multi_no_python = F.LookupField[str](
        "Prog. Lang. Multi — No Python (from Current Prompt)"
    )
    prog_lang_multi_with_python = F.LookupField[str](
        "Prog. Lang. Multi — With Python (from Current Prompt)"
    )
    hide_prompt = F.CheckboxField("Hide Prompt")
    use_latex = F.CheckboxField("Use LaTeX")
    file_search = F.CheckboxField("Enable File Search")
    code_interpreter = F.CheckboxField("Enable Code Interpreter")
    publish = F.CheckboxField("Publish")

    class Meta:
        table_name: str = "Assistant Templates"
        base_id: str = _AIRTABLE_NONSTUDY_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class PingPongAssistant(Model):
    pingpong_id = F.NumberField("ID")
    template = F.SingleLinkField("Assistant Template", AssistantTemplate)
    update_to = F.SingleLinkField("Update To Template", AssistantTemplate)
    pp_class = F.SingleLinkField("PingPong Class", "PingPongClass")
    pp_class_id = F.LookupField[str]("PingPong ID")
    status = F.SelectField("Status")
    status_notes = F.TextField("Status Notes")

    class Meta:
        table_name: str = "PingPong Assistants"
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class PingPongAssistantNonStudy(Model):
    pingpong_id = F.NumberField("ID")
    template = F.SingleLinkField("Assistant Template", AssistantTemplateNonStudy)

    class Meta:
        table_name: str = "PingPong Assistants"
        base_id: str = _AIRTABLE_NONSTUDY_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class UserClassRole(Model):
    email = F.TextField("Email (from User)", readonly=True)
    class_id = F.LookupField[str]("PingPong ID (from Class)")
    status = F.SelectField("Status")
    status_notes = F.TextField("Status Notes")

    class Meta:
        table_name: str = "PingPong UserRecords"
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class ExternalLoginRequests(Model):
    current_email = F.EmailField("Primary Email")
    new_email = F.EmailField("Login Email")
    status = F.SelectField("Status")
    status_notes = F.TextField("Status Notes")

    class Meta:
        table_name: str = "PingPong ExternalLogins"
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class InstructorNonStudy(Model):
    email = F.EmailField("Email")

    class Meta:
        table_name: str = "Instructors"
        base_id: str = _AIRTABLE_NONSTUDY_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class ExternalLoginRequestsNonStudy(Model):
    current_email = F.EmailField("Primary Email")
    new_email = F.EmailField("Login Email")
    status = F.SelectField("Status")
    status_notes = F.TextField("Status Notes")
    instructor = F.LinkField("Instructor Record", InstructorNonStudy)

    class Meta:
        table_name: str = "PingPong ExternalLogins"
        base_id: str = _AIRTABLE_NONSTUDY_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class PingPongClass(Model):
    status = F.SelectField("Status")
    update_status = F.SelectField("Update Class Status")
    status_notes = F.TextField("Status Notes")
    pingpong_id = F.TextField("PingPong ID")
    class_name = F.LookupField[str]("Class Name")
    class_term = F.TextField("Class Term")
    class_institution = F.TextField("Class Institution")
    class_programming_languages = F.MultipleSelectField(
        "Programming Languages (from Qualtrics Class)"
    )
    teacher_email = F.LookupField[F.EmailField]("Teacher Email")
    billing_provider = F.SelectField("Billing Provider")
    billing_api_key = F.TextField("Billing API Selection")
    assistant_templates = F.LinkField("Assistant Templates", AssistantTemplate)
    pingpong_assistants = F.LinkField("PingPong Assistants", PingPongAssistant)
    remove_admin = F.CheckboxField("Remove Admin")

    class Meta:
        table_name: str = "PingPong Classes"
        base_id: str = _AIRTABLE_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class PingPongClassNonStudy(Model):
    status = F.SelectField("Status")
    update_status = F.SelectField("Update Class Status")
    status_notes = F.TextField("Status Notes")
    pingpong_id = F.TextField("PingPong ID")
    class_name = F.LookupField[str]("Class Name")
    class_term = F.TextField("Class Term")
    class_institution = F.TextField("Class Institution")
    class_programming_languages = F.MultipleSelectField(
        "Programming Languages (from Qualtrics Class)"
    )
    teacher_email = F.LookupField[F.EmailField]("Teacher Email")
    teacher_personal_email = F.LookupField[F.EmailField]("Teacher Personal Email")
    teacher_id = F.LookupField[str]("Teacher ID")
    billing_provider = F.SelectField("Billing Provider")
    billing_api_key = F.TextField("Billing API Selection")
    assistant_templates = F.LinkField("Assistant Templates", AssistantTemplateNonStudy)
    pingpong_assistants = F.LinkField("PingPong Assistants", PingPongAssistantNonStudy)
    remove_admin = F.CheckboxField("Remove Admin")

    class Meta:
        table_name: str = "PingPong Classes"
        base_id: str = _AIRTABLE_NONSTUDY_BASE_ID
        api_key: str = _AIRTABLE_API_KEY


class Tool(BaseModel):
    type: str


class CreateAssistant(BaseModel):
    name: str
    code_interpreter_file_ids: list[str] = []
    file_search_file_ids: list[str] = []
    instructions: str
    description: str
    model: str
    temperature: float
    tools: list[Tool]
    published: bool
    use_latex: bool
    hide_prompt: bool
    use_image_descriptions: bool = False


class UpdateAssistant(BaseModel):
    name: str
    code_interpreter_file_ids: list[str] = []
    file_search_file_ids: list[str] = []
    instructions: str
    description: str
    model: str
    temperature: float
    tools: list[Tool]
    published: bool | None = None
    use_latex: bool
    hide_prompt: bool
    use_image_descriptions: bool = False
