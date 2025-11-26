from datetime import datetime
from pyairtable.orm import Model, fields as F
from typing import Literal, cast

from pydantic import BaseModel
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
    profile_notice_seen_sep_25 = F.CheckboxField("notice.profile_moved.v1")

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
    end_date = F.DateField("End Date")
    enrollment_count = F.NumberField("Enrollment")
    completion_rate_target = F.NumberField("Completion Target (Public)")
    preassessment_url = F.UrlField("Pre-Assessment URL")
    postassessment_url = F.UrlField("PostAssessment Link")
    postassessment_status = F.SelectField("PostAssessment")
    pingpong_group_url = F.UrlField("PingPong Group URL")
    instructor = F.LookupField[Instructor]("Instructor", readonly=True)
    preassessment_student_count = F.NumberField("Pre-Assessment Student Count")
    postassessment_student_count = F.NumberField("Post: Student Count")

    class Meta:
        api_key = study_config.airtable_api_key
        base_id = study_config.airtable_base_id
        table_name = study_config.airtable_class_table_id


class PreAssessmentStudentSubmission(Model):
    """Airtable pre-assessment student submission model."""

    submission_id = F.RequiredSingleLineTextField("Response ID")
    status = F.SelectField("Automation Status")
    first_name = F.SingleLineTextField("First Name")
    last_name = F.SingleLineTextField("Last Name")
    email = F.EmailField("Academic Email")
    submitted_at = F.DatetimeField("Completed At (ET)")
    course_id = F.LookupField[Course]("Class", readonly=True)
    student_id = F.TextField("Student ID", readonly=True)
    class_id = F.TextField("Class ID", readonly=True)
    removal_status = F.LookupField[str]("Exclude Status", readonly=True)

    class Meta:
        api_key = study_config.airtable_api_key
        base_id = study_config.airtable_base_id
        table_name = study_config.airtable_preassessment_submission_table_id


class PostAssessmentStudentSubmission(Model):
    """Airtable post-assessment student submission model."""

    submission_id = F.RequiredSingleLineTextField("Response ID")
    status = F.SelectField("Status")
    course_id = F.LookupField[Course]("Class Link", readonly=True)
    student_id = F.TextField("Student ID", readonly=True)
    submitted_at = F.DatetimeField("Completed At (ET)")
    name = F.SingleLineTextField("Name")
    email = F.EmailField("Email")
    error_type = F.SelectField("Type")

    class Meta:
        api_key = study_config.airtable_api_key
        base_id = study_config.airtable_base_id
        table_name = study_config.airtable_postassessment_submission_table_id


class PreAssessmentStudentSubmissionResponse(BaseModel):
    """Response model for pre-assessment student submission."""

    id: str
    first_name: str
    last_name: str
    email: str
    submission_date: datetime
    student_id: str | None = None
    class_id: str | None = None
    removed: bool = False


class PostAssessmentStudentSubmissionResponse(BaseModel):
    """Response model for post-assessment student submission."""

    id: str
    name: str
    email: str
    submission_date: datetime
    student_id: str | None = None
    class_id: str | None = None
    status: Literal["OK", "PEND", "NRC", "PRE"] | None = "PEND"
    removed: bool = False


class PreAssessmentStudentSubmissionsResponse(BaseModel):
    """Response model for pre-assessment student submissions."""

    pre_assessment_submissions: list[PreAssessmentStudentSubmissionResponse]
    post_assessment_submissions: list[PostAssessmentStudentSubmissionResponse]


class UpdateEnrollmentRequest(BaseModel):
    """Request body for updating a course's enrollment count."""

    enrollment_count: int


class Admin(Model):
    """Airtable admin model."""

    record_id = F.RequiredSingleLineTextField("ID")
    email = F.EmailField("Email")
    first_name = F.SingleLineTextField("First Name")

    class Meta:
        api_key = study_config.airtable_api_key
        base_id = study_config.airtable_base_id
        table_name = study_config.airtable_admin_table_id


class UserClassAssociation(Model):
    """Airtable user/group association model."""

    record_id = F.RequiredSingleLineTextField("ID")
    student_id = F.LookupField[str]("Student ID", readonly=True)
    class_id = F.LookupField[str]("Airtable Class ID", readonly=True)
    removal_status = F.SelectField("Exclude Status")

    class Meta:
        api_key = study_config.airtable_api_key
        base_id = study_config.airtable_base_id
        table_name = study_config.airtable_user_class_association_table_id
