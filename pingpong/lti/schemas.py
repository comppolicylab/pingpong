from typing import Literal
from pydantic import BaseModel, Field


class LTIPublicSSOProvider(BaseModel):
    id: int
    name: str
    display_name: str | None


class LTIPublicSSOProviders(BaseModel):
    providers: list[LTIPublicSSOProvider]


class LTIPublicInstitution(BaseModel):
    id: int
    name: str


class LTIPublicInstitutions(BaseModel):
    institutions: list[LTIPublicInstitution]


LTISSOField = Literal[
    "canvas.sisIntegrationId",
    "canvas.sisSourceId",
    "person.sourcedId",
]


class LTIRegisterRequest(BaseModel):
    name: str
    admin_name: str
    admin_email: str
    provider_id: int
    sso_field: LTISSOField | None = None
    openid_configuration: str
    registration_token: str
    institution_ids: list[int] = Field(min_length=1)
    show_in_course_navigation: bool = True


# LTI Setup schemas
class LTISetupInstitution(BaseModel):
    id: int
    name: str


class LTISetupContext(BaseModel):
    lti_class_id: int
    course_name: str | None
    course_code: str | None
    course_term: str | None
    institutions: list[LTISetupInstitution]


class LTILinkableGroup(BaseModel):
    id: int
    name: str
    term: str
    institution_name: str


class LTILinkableGroupsResponse(BaseModel):
    groups: list[LTILinkableGroup]


class LTISetupCreateRequest(BaseModel):
    institution_id: int
    name: str
    term: str


class LTISetupCreateResponse(BaseModel):
    class_id: int


class LTISetupLinkRequest(BaseModel):
    class_id: int


class LTISetupLinkResponse(BaseModel):
    class_id: int
