from datetime import datetime
from enum import Enum, StrEnum, auto

from openai.types.beta.assistant_create_params import Tool
from openai.types.beta.threads import Run as OpenAIRun
from openai.types.beta.threads import ThreadMessage as OpenAIMessage
from pydantic import BaseModel, Field, SecretStr

from .gravatar import get_email_hash, get_gravatar_image


class GenericStatus(BaseModel):
    status: str


class Profile(BaseModel):
    email: str
    gravatar_id: str
    image_url: str

    @classmethod
    def from_email(cls, email: str) -> "Profile":
        """Return a profile from an email address."""
        hashed = get_email_hash(email)
        return cls(
            email=email,
            gravatar_id=hashed,
            image_url=get_gravatar_image(email),
        )


class File(BaseModel):
    id: int
    name: str
    content_type: str
    file_id: str
    class_id: int
    private: bool | None
    uploader_id: int | None
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class Files(BaseModel):
    files: list[File]

    class Config:
        from_attributes = True


class Assistant(BaseModel):
    id: int
    name: str
    instructions: str
    description: str | None
    tools: str
    model: str
    class_id: int
    creator_id: int
    files: list[File]
    use_latex: bool | None
    hide_prompt: bool | None
    published: datetime | None
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class CreateAssistant(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    file_ids: list[str]
    instructions: str = Field(..., min_length=3)
    description: str
    model: str = Field(..., min_length=3)
    tools: list[Tool]
    published: bool = False
    use_latex: bool = False
    hide_prompt: bool = False


class UpdateAssistant(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)
    file_ids: list[str] | None = None
    instructions: str | None = Field(None, min_length=3)
    description: str | None = None
    model: str | None = Field(None, min_length=3)
    tools: list[Tool] | None = None
    published: bool | None = None
    use_latex: bool | None = None
    hide_prompt: bool | None = None


class Assistants(BaseModel):
    assistants: list[Assistant]
    creators: dict[int, Profile]

    class Config:
        from_attributes = True


class UserPlaceholder(BaseModel):
    id: int
    email: str


class Thread(BaseModel):
    id: int
    name: str
    thread_id: str
    class_id: int
    assistant_id: int
    private: bool
    users: list["UserPlaceholder"]
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class CreateThread(BaseModel):
    parties: list[int] = []
    message: str = Field(..., min_length=1)
    assistant_id: int
    file_ids: list[str] = Field([], min_items=0, max_items=10)


class NewThreadMessage(BaseModel):
    message: str = Field(..., min_length=1)
    file_ids: list[str] = Field([], min_items=0, max_items=10)


class Threads(BaseModel):
    threads: list[Thread]

    class Config:
        from_attributes = True


class Role(Enum):
    ADMIN = "admin"
    WRITE = "write"
    READ = "read"


class CreateUserClassRole(BaseModel):
    email: str = Field(..., min_length=3, max_length=100)
    role: Role
    title: str = Field(..., min_length=3, max_length=24)


class CreateUserClassRoles(BaseModel):
    roles: list[CreateUserClassRole]
    silent: bool = False


class UserClassRole(BaseModel):
    user_id: int
    class_id: int
    role: Role
    title: str

    class Config:
        from_attributes = True


class UserClassRoles(BaseModel):
    roles: list[UserClassRole]


class UpdateUserClassRole(BaseModel):
    role: Role
    title: str = Field(..., min_length=3, max_length=24)


class CreateInvite(BaseModel):
    user_id: int
    email: str = Field(..., min_length=3, max_length=100)
    class_name: str = Field(..., min_length=3, max_length=100)


class UserState(Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    BANNED = "banned"


class User(BaseModel):
    id: int
    name: str | None
    email: str
    state: UserState
    classes: list["UserClassRole"]
    institutions: list["Institution"]
    super_admin: bool
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class ClassUser(BaseModel):
    id: int
    name: str | None
    email: str
    state: UserState
    role: Role
    title: str


class ClassUsers(BaseModel):
    users: list[ClassUser]

    class Config:
        from_attributes = True


class CreateInstitution(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)


class Institution(BaseModel):
    id: int
    name: str
    description: str | None
    logo: str | None
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class Institutions(BaseModel):
    institutions: list[Institution]

    class Config:
        from_attributes = True


class Class(BaseModel):
    id: int
    name: str
    term: str
    institution_id: int
    institution: Institution | None = None
    created: datetime
    updated: datetime | None
    api_key: SecretStr | None
    any_can_create_assistant: bool | None = None
    any_can_publish_assistant: bool | None = None

    class Config:
        from_attributes = True


class CreateClass(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    term: str = Field(..., min_length=1, max_length=100)
    any_can_create_assistant: bool = False
    any_can_publish_assistant: bool = False


class UpdateClass(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)
    term: str | None = Field(None, min_length=1, max_length=100)
    any_can_create_assistant: bool | None = None
    any_can_publish_assistant: bool | None = None


class UpdateApiKey(BaseModel):
    api_key: str


class ApiKey(BaseModel):
    api_key: str | None


class AssistantModel(BaseModel):
    id: str
    created: datetime
    owner: str


class AssistantModels(BaseModel):
    models: list[AssistantModel]


class Classes(BaseModel):
    classes: list[Class]

    class Config:
        from_attributes = True


class ThreadRun(BaseModel):
    thread: Thread
    run: OpenAIRun | None

    class Config:
        from_attributes = True


class ThreadParticipants(BaseModel):
    user: dict[int, Profile]
    assistant: dict[int, str]


class ThreadWithMeta(BaseModel):
    thread: Thread
    hash: str
    run: OpenAIRun | None
    messages: list[OpenAIMessage]
    participants: ThreadParticipants

    class Config:
        from_attributes = True


class AuthToken(BaseModel):
    """Auth Token - minimal token used to log in."""

    sub: str
    exp: int
    iat: int


class SessionToken(BaseModel):
    """Session Token - stores information about user for a session."""

    sub: str
    exp: int
    iat: int


class SessionStatus(StrEnum):
    VALID = auto()
    MISSING = auto()
    INVALID = auto()
    ERROR = auto()


class SessionState(BaseModel):
    status: SessionStatus
    error: str | None = None
    token: SessionToken | None = None
    user: User | None = None
    profile: Profile | None = None


class Support(BaseModel):
    blurb: str
    can_post: bool


class SupportRequest(BaseModel):
    email: str | None = None
    name: str | None = None
    category: str | None = None
    message: str = Field(..., min_length=1, max_length=1000)
