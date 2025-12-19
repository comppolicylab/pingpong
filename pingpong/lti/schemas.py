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
