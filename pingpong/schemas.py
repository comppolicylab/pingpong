from datetime import datetime
from enum import Enum, StrEnum, auto
from typing import Literal, Union, TypedDict

from openai.types.beta.assistant_tool import AssistantTool as Tool
from openai.types.beta.threads import Message as OpenAIMessage
from pydantic import BaseModel, Field, SecretStr, computed_field

from .gravatar import get_email_hash, get_gravatar_image


class GenericStatus(BaseModel):
    status: str


class ManageAuthzRequest(BaseModel):
    grant: list[tuple[str, str, str]] = []
    revoke: list[tuple[str, str, str]] = []


class AuthzEntity(BaseModel):
    id: int | None = None
    type: str


class InspectAuthzTestResult(BaseModel):
    test: Literal["test"] = "test"
    verdict: bool


class InspectAuthzListResult(BaseModel):
    test: Literal["list"] = "list"
    list: list[int]


class InspectAuthzErrorResult(BaseModel):
    test: Literal["error"] = "error"
    error: str


InspectAuthzResult = Union[
    InspectAuthzTestResult, InspectAuthzListResult, InspectAuthzErrorResult
]


class InspectAuthz(BaseModel):
    subject: AuthzEntity
    relation: str
    object: AuthzEntity
    result: InspectAuthzResult


class MagicLoginRequest(BaseModel):
    email: str


class Profile(BaseModel):
    name: str | None
    email: str
    gravatar_id: str
    image_url: str

    @classmethod
    def from_email(cls, email: str) -> "Profile":
        """Return a profile from an email address."""
        hashed = get_email_hash(email)
        return cls(
            name=None,
            email=email,
            gravatar_id=hashed,
            image_url=get_gravatar_image(email),
        )

    @classmethod
    def from_user(cls, user: "User") -> "Profile":
        """Return a profile from an email address and name."""
        hashed = get_email_hash(user.email)
        name = (
            user.display_name
            if user.display_name
            else " ".join(filter(None, [user.first_name, user.last_name])) or user.email
        )
        return cls(
            name=name,
            email=user.email,
            gravatar_id=hashed,
            image_url=get_gravatar_image(user.email),
        )


class UserState(Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    BANNED = "banned"


class UserNameMixin:
    email: str
    first_name: str | None
    last_name: str | None
    display_name: str | None

    @computed_field  # type: ignore
    @property
    def name(self) -> str:
        """Return some kind of name for the user."""
        if self.display_name:
            return self.display_name
        parts = [name for name in [self.first_name, self.last_name] if name]
        if not parts:
            return self.email
        return " ".join(parts)


class User(BaseModel, UserNameMixin):
    id: int
    state: UserState
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


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


class AssistantFiles(BaseModel):
    code_interpreter_files: list[File]
    file_search_files: list[File]

    class Config:
        from_attributes = True


class AssistantFilesResponse(BaseModel):
    files: AssistantFiles

    class Config:
        from_attributes = True


FileUploadPurpose = Union[Literal["assistants"], Literal["vision"], Literal["multimodal"]]


class VectorStore(BaseModel):
    id: int
    vector_store_id: str
    type: str
    class_id: int
    uploader_id: int
    expires_at: datetime | None
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class VectorStoreType(Enum):
    ASSISTANT = "assistant"
    THREAD = "thread"


class Assistant(BaseModel):
    id: int
    name: str
    instructions: str
    description: str | None
    tools: str
    model: str
    class_id: int
    creator_id: int
    use_latex: bool | None
    hide_prompt: bool | None
    published: datetime | None
    endorsed: bool | None = None
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class CreateAssistant(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    code_interpreter_file_ids: list[str] | None = None
    file_search_file_ids: list[str] | None = None
    instructions: str = Field(..., min_length=3)
    description: str
    model: str = Field(..., min_length=3)
    tools: list[Tool]
    published: bool = False
    use_latex: bool = False
    hide_prompt: bool = False
    deleted_private_files: list[int] = []


class UpdateAssistant(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)
    code_interpreter_file_ids: list[str] | None = None
    file_search_file_ids: list[str] | None = None
    instructions: str | None = Field(None, min_length=3)
    description: str | None = None
    model: str | None = Field(None, min_length=3)
    tools: list[Tool] | None = None
    published: bool | None = None
    use_latex: bool | None = None
    hide_prompt: bool | None = None
    deleted_private_files: list[int] = []


class DeleteAssistant(BaseModel):
    has_code_interpreter_files: bool = False
    private_files: list[int] = []


class Assistants(BaseModel):
    assistants: list[Assistant]
    creators: dict[int, User]

    class Config:
        from_attributes = True


class Thread(BaseModel):
    id: int
    name: str
    thread_id: str
    class_id: int
    assistant_names: dict[int, str] = {}
    assistant_id: int | None = None
    private: bool
    tools_available: str | None
    user_names: list[str] = []
    created: datetime
    updated: datetime | None

    class Config:
        from_attributes = True


class CreateThread(BaseModel):
    parties: list[int] = []
    message: str = Field(..., min_length=1)
    code_interpreter_file_ids: list[str] = Field([], min_length=0, max_length=10)
    file_search_file_ids: list[str] = Field([], min_length=0, max_length=10)
    vision_file_ids: list[str] = Field([], min_length=0, max_length=10)
    tools_available: list[Tool]
    assistant_id: int


class NewThreadMessage(BaseModel):
    message: str = Field(..., min_length=1)
    file_search_file_ids: list[str] = Field([], min_length=0, max_length=10)
    code_interpreter_file_ids: list[str] = Field([], min_length=0, max_length=10)
    vision_file_ids: list[str] = Field([], min_length=0, max_length=10)


class Threads(BaseModel):
    threads: list[Thread]

    class Config:
        from_attributes = True


class Role(Enum):
    """Possible user roles.

    @deprecated This role enum is deprecated. Use ClassUserRoles instead,
    along with the new permissions system.
    """

    ADMIN = "admin"
    WRITE = "write"
    READ = "read"


class ClassUserRoles(BaseModel):
    admin: bool
    teacher: bool
    student: bool

    def string(self) -> str:
        return f"admin={self.admin},teacher={self.teacher},student={self.student}"


class CreateUserClassRole(BaseModel):
    email: str = Field(..., min_length=3, max_length=100)
    roles: ClassUserRoles


class CreateUserClassRoles(BaseModel):
    roles: list[CreateUserClassRole]
    silent: bool = False


class UserClassRole(BaseModel):
    user_id: int
    class_id: int
    roles: ClassUserRoles

    class Config:
        from_attributes = True


class UserClassRoles(BaseModel):
    roles: list[UserClassRole]


class UpdateUserClassRole(BaseModel):
    role: Literal["admin"] | Literal["teacher"] | Literal["student"] | None


class CreateInvite(BaseModel):
    user_id: int
    inviter_name: str | None
    email: str = Field(..., min_length=3, max_length=100)
    class_name: str = Field(..., min_length=3, max_length=100)
    formatted_role: str | None = None


class UpdateUserInfo(BaseModel):
    """Fields that the user can edit about themselves."""

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    display_name: str | None = Field(None, min_length=1, max_length=100)


class ClassUser(BaseModel):
    id: int
    first_name: str | None
    last_name: str | None
    display_name: str | None
    email: str
    state: UserState
    roles: ClassUserRoles
    explanation: list[list[str]] | None


class UserGroup(BaseModel):
    name: str
    explanation: list[list[str]] | None


class ClassUsers(BaseModel):
    users: list[ClassUser]
    limit: int
    offset: int
    total: int

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
    private: bool | None = None
    any_can_create_assistant: bool | None = None
    any_can_publish_assistant: bool | None = None
    any_can_publish_thread: bool | None = None
    any_can_upload_class_file: bool | None = None

    class Config:
        from_attributes = True


class CreateClass(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    term: str = Field(..., min_length=1, max_length=100)
    private: bool = False
    any_can_create_assistant: bool = False
    any_can_publish_assistant: bool = False
    any_can_publish_thread: bool = False
    any_can_upload_class_file: bool = False


class UpdateClass(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)
    term: str | None = Field(None, min_length=1, max_length=100)
    private: bool | None = None
    any_can_create_assistant: bool | None = None
    any_can_publish_assistant: bool | None = None
    any_can_publish_thread: bool | None = None
    any_can_upload_class_file: bool | None = None


class UpdateApiKey(BaseModel):
    api_key: str


class ApiKey(BaseModel):
    api_key: str | None


class AssistantModel(BaseModel):
    id: str
    created: datetime
    owner: str
    name: str
    description: str
    is_latest: bool
    is_new: bool
    highlight: bool
    supports_vision: bool


class AssistantModelDict(TypedDict):
    name: str
    sort_order: int
    is_latest: bool
    is_new: bool
    highlight: bool
    supports_vision: bool
    description: str


class AssistantModels(BaseModel):
    models: list[AssistantModel]


class Classes(BaseModel):
    classes: list[Class]

    class Config:
        from_attributes = True


class OpenAIRunError(BaseModel):
    code: str
    message: str


class OpenAIRun(BaseModel):
    # See OpenAI's Run type. We select a subset of fields.
    id: str
    assistant_id: str
    cancelled_at: int | None
    completed_at: int | None
    created_at: int
    expires_at: int | None
    failed_at: int | None
    instructions: SecretStr
    last_error: OpenAIRunError | None
    metadata: dict[str, str]
    model: str
    object: Literal["thread.run"]
    status: (
        Literal["queued"]
        | Literal["in_progress"]
        | Literal["requires_action"]
        | Literal["cancelling"]
        | Literal["cancelled"]
        | Literal["failed"]
        | Literal["completed"]
        | Literal["expired"]
    )
    thread_id: str
    tools: list[Tool]
    # required_action // not shown
    # usage // not shown


class ImageFile(BaseModel):
    file_id: str


class MessageContentCodeOutputImageFile(BaseModel):
    image_file: ImageFile
    type: Literal["code_output_image_file"]


class MessageContentCode(BaseModel):
    code: str
    type: Literal["code"]


CodeInterpreterMessageContent = Union[
    MessageContentCodeOutputImageFile, MessageContentCode
]


class CodeInterpreterPlaceholderContent(BaseModel):
    run_id: str
    step_id: str
    thread_id: str
    type: Literal["code_interpreter_call_placeholder"]


class CodeInterpreterMessage(BaseModel):
    id: str
    assistant_id: str
    created_at: int
    content: (
        list[CodeInterpreterMessageContent] | list[CodeInterpreterPlaceholderContent]
    )
    metadata: dict[str, str]
    object: Literal["thread.message"] | Literal["code_interpreter_call_placeholder"]
    role: Literal["assistant"]
    run_id: str
    thread_id: str


class CodeInterpreterMessages(BaseModel):
    ci_messages: list[CodeInterpreterMessage]


class ThreadRun(BaseModel):
    thread: Thread
    run: OpenAIRun | None

    class Config:
        from_attributes = True


class ThreadParticipants(BaseModel):
    user: list[str]
    assistant: dict[int, str]


class ThreadMessages(BaseModel):
    limit: int
    messages: list[OpenAIMessage]
    ci_messages: list[CodeInterpreterMessage] | None


class ThreadWithMeta(BaseModel):
    thread: Thread
    model: str
    tools_available: str
    run: OpenAIRun | None
    messages: list[OpenAIMessage]
    limit: int
    ci_messages: list[CodeInterpreterMessage] | None

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


class FileTypeInfo(BaseModel):
    name: str
    mime_type: str
    file_search: bool
    code_interpreter: bool
    vision: bool
    extensions: list[str]


class FileUploadSupport(BaseModel):
    types: list[FileTypeInfo]
    allow_private: bool
    private_file_max_size: int
    class_file_max_size: int


class GrantQuery(BaseModel):
    target_type: str
    target_id: int
    relation: str


class GrantsQuery(BaseModel):
    grants: list[GrantQuery]


class GrantDetail(BaseModel):
    request: GrantQuery
    verdict: bool


class Grants(BaseModel):
    grants: list[GrantDetail]


class GrantsList(BaseModel):
    subject_type: str
    subject_id: int
    target_type: str
    relation: str
    target_ids: list[int]
