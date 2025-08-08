from pyairtable.orm import Model, fields as F
from pingpong.config import config


class Instructor(Model):
    """Airtable instructor model."""

    record_id = F.RequiredSingleLineTextField("ID")
    first_name = F.SingleLineTextField("First Name")
    last_name = F.SingleLineTextField("Last Name")
    academic_email = F.EmailField("Academic Email")
    personal_email = F.EmailField("Personal Email")
    honorarium_status = F.SelectField("Honorarium?")
    mailing_address = F.RichTextField("Mailing Address")
    institution = F.LookupField[str]("Institution Name", readonly=True)

    class Meta:
        api_key = config.study.airtable_api_key
        base_id = config.study.airtable_base_id
        table_name = config.study.airtable_instructor_table_id


class Course(Model):
    """Airtable course model."""

    record_id = F.RequiredSingleLineTextField("ID")
    name = F.SingleLineTextField("Name")
    status = F.SelectField("Review Status")
    randomization = F.SelectField("Randomization Result")
    start_date = F.DateField("Start Date")
    enrollment_count = F.NumberField("Enrollment")
    preassessment_url = F.UrlField("Pre-Assessment URL")
    pingpong_group_url = F.UrlField("PingPong Group URL")
    instructor = F.LookupField[Instructor]("Instructor", readonly=True)

    class Meta:
        api_key = config.study.airtable_api_key
        base_id = config.study.airtable_base_id
        table_name = config.study.airtable_class_table_id
