from pyairtable.orm import Model, fields as F
from typing import cast
from pingpong.config import config, StudySettings

# Ensure study config is available at import time for Airtable models
if config.study is None:
    raise ValueError("Study settings are not configured")
study_config = cast(StudySettings, config.study)


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
        api_key = study_config.airtable_api_key
        base_id = study_config.airtable_base_id
        table_name = study_config.airtable_instructor_table_id


class Course(Model):
    """Airtable course model."""

    record_id = F.RequiredSingleLineTextField("ID")
    name = F.SingleLineTextField("Name")
    status = F.SelectField("Review Status")
    randomization = F.SelectField("Randomization Result")
    start_date = F.DateField("Start Date")
    enrollment_count = F.NumberField("Enrollment")
    completion_rate_target = F.NumberField("Completion Target (Public)")
    preassessment_url = F.UrlField("Pre-Assessment URL")
    pingpong_group_url = F.UrlField("PingPong Group URL")
    instructor = F.LookupField[Instructor]("Instructor", readonly=True)

    class Meta:
        api_key = study_config.airtable_api_key
        base_id = study_config.airtable_base_id
        table_name = study_config.airtable_class_table_id


class Admin(Model):
    """Airtable admin model."""

    record_id = F.RequiredSingleLineTextField("ID")
    email = F.EmailField("Email")
    first_name = F.SingleLineTextField("First Name")

    class Meta:
        api_key = study_config.airtable_api_key
        base_id = study_config.airtable_base_id
        table_name = study_config.airtable_admin_table_id
