from pydantic import BaseModel


class LTIRegisterRequest(BaseModel):
    name: str
    admin_name: str
    admin_email: str
    provider_id: int
    openid_configuration: str
    registration_token: str