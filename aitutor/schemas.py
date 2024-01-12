from datetime import datetime
from enum import Enum, StrEnum, auto

from openai.types.beta.assistant_create_params import Tool
from openai.types.beta.threads import Run as OpenAIRun
from openai.types.beta.threads import ThreadMessage as OpenAIMessage
from pydantic import BaseModel, SecretStr

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
    tools: str
    model: str
    class_id: int
    creator_id: int
    files: list[File]
    published: datetime | None
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class CreateAssistant(BaseModel):
    name: str
    file_ids: list[str]
    instructions: str
    model: str
    tools: list[Tool]
    published: bool = False


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
    message: str
    assistant_id: int


class Threads(BaseModel):
    threads: list[Thread]

    class Config:
        from_attributes = True


class Role(Enum):
    ADMIN = "admin"
    WRITE = "write"
    READ = "read"


class CreateUserClassRole(BaseModel):
    email: str
    role: Role
    title: str


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
    title: str


class CreateInvite(BaseModel):
    user_id: int
    email: str
    class_name: str


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

    class Config:
        from_attributes = True


class CreateClass(BaseModel):
    name: str
    term: str
    institution_id: int


class UpdateClass(BaseModel):
    name: str | None = None
    term: str | None = None


class UpdateApiKey(BaseModel):
    api_key: str


class ApiKey(BaseModel):
    api_key: str | None


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
