from datetime import datetime
from enum import Enum, StrEnum, auto
from typing import Generic, Literal, TypeVar, Union, TypedDict

from openai.types.beta.assistant_tool import AssistantTool as Tool
from openai.types.beta.threads import Message as OpenAIMessage
from pydantic import BaseModel, Field, SecretStr, computed_field, model_validator
from .gravatar import get_email_hash, get_gravatar_image


class Statistics(BaseModel):
    """Statistics about the system."""

    institutions: int
    classes: int
    users: int
    enrollments: int
    assistants: int
    threads: int
    files: int


class StatisticsResponse(BaseModel):
    """Statistics response."""

    statistics: Statistics


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
    forward: str = "/"


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

    @computed_field  # type: ignore
    @property
    def has_real_name(self) -> bool:
        """Return whether we have a name to display for a user."""
        return bool(self.display_name or self.first_name or self.last_name)


class MergedUserTuple(BaseModel):
    current_user_id: int
    merged_user_id: int


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
    vision_obj_id: int | None = None
    file_search_file_id: str | None = None
    code_interpreter_file_id: str | None = None
    vision_file_id: str | None = None
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


FileUploadPurpose = Union[
    Literal["assistants"],
    Literal["vision"],
    Literal["fs_ci_multimodal"],
    Literal["fs_multimodal"],
    Literal["ci_multimodal"],
]


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


class VectorStoreDeleteResponse(BaseModel):
    vector_store_id: str
    deleted_file_ids: list[int]

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
    temperature: float
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
    temperature: float = Field(1.0, ge=0.0, le=2.0)
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
    temperature: float | None = Field(None, ge=0.0, le=2.0)
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
    name: str | None
    thread_id: str
    class_id: int
    assistant_names: dict[int, str] = {}
    assistant_id: int | None = None
    private: bool
    tools_available: str | None
    user_names: list[str] = []
    created: datetime
    last_activity: datetime

    class Config:
        from_attributes = True


def file_validator(self):
    if (
        len(
            set(self.file_search_file_ids or []).union(
                set(self.code_interpreter_file_ids or [])
            )
        )
        > 10
    ) or len(self.vision_file_ids) > 10:
        raise ValueError("You cannot upload more than 10 files in a single message.")
    return self


class CreateThread(BaseModel):
    parties: list[int] = []
    message: str = Field(..., min_length=1)
    code_interpreter_file_ids: list[str] = Field([])
    file_search_file_ids: list[str] = Field([])
    vision_file_ids: list[str] = Field([])
    tools_available: list[Tool]
    assistant_id: int

    _file_check = model_validator(mode="after")(file_validator)


class ThreadName(BaseModel):
    name: str | None
    can_generate: bool


class NewThreadMessage(BaseModel):
    message: str = Field(..., min_length=1)
    code_interpreter_file_ids: list[str] = Field([])
    file_search_file_ids: list[str] = Field([])
    vision_file_ids: list[str] = Field([])

    _file_check = model_validator(mode="after")(file_validator)


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
    display_name: str | None = None
    sso_id: str | None = None
    roles: ClassUserRoles


class LMSType(Enum):
    CANVAS = "canvas"


class CreateUserResult(BaseModel):
    id: int | None = None
    email: str
    display_name: str | None = None
    error: str | None = None


class CreateUserResults(BaseModel):
    results: list[CreateUserResult]


class UserClassRole(BaseModel):
    user_id: int
    class_id: int
    lms_tenant: str | None = None
    lms_type: LMSType | None = None
    roles: ClassUserRoles

    class Config:
        from_attributes = True


class UserClassRoles(BaseModel):
    roles: list[UserClassRole]


class EmailValidationRequest(BaseModel):
    emails: str


class EmailValidationResult(BaseModel):
    email: str
    valid: bool
    isUser: bool = False
    name: str | None
    error: str | None = None


class EmailValidationResults(BaseModel):
    results: list[EmailValidationResult]


class UpdateUserClassRole(BaseModel):
    role: Literal["admin"] | Literal["teacher"] | Literal["student"] | None


class CreateInvite(BaseModel):
    user_id: int
    inviter_name: str | None
    email: str = Field(..., min_length=3, max_length=100)
    class_name: str = Field(..., min_length=3, max_length=100)
    formatted_role: str | None = None


class DownloadExport(BaseModel):
    link: str
    email: str
    class_name: str


class CreateUserInviteConfig(BaseModel):
    invites: list[CreateInvite] = []
    formatted_roles: dict[str, str] = {}
    inviter_display_name: str | None = None


class UpdateUserInfo(BaseModel):
    """Fields that the user can edit about themselves."""

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    display_name: str | None = Field(None, min_length=1, max_length=100)


class ClassUser(BaseModel, UserNameMixin):
    id: int
    state: UserState
    roles: ClassUserRoles
    explanation: list[list[str]] | None
    lms_tenant: str | None = None
    lms_type: LMSType | None = None


class UserGroup(BaseModel):
    name: str
    explanation: list[list[str]] | None


class SupervisorUser(BaseModel):
    name: str | None = None
    email: str


class ClassSupervisors(BaseModel):
    users: list[SupervisorUser]


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


# Status documenting the state of the LMS sync.
# NONE: The user has not authorized the app to sync with LMS.
# AUTHORIZED: The user has authorized the app to sync with LMS.
# LINKED: The user has linked the LMS course to the class.
# DISMISSED: The user has dismissed the LMS sync dialog.
# ERROR: There was an error during the LMS sync. The user should try again.
class LMSStatus(StrEnum):
    NONE = auto()
    AUTHORIZED = auto()
    LINKED = auto()
    DISMISSED = auto()
    ERROR = auto()


class CreateUserClassRoles(BaseModel):
    roles: list[CreateUserClassRole]
    silent: bool = False
    lms_tenant: str | None = None
    lms_type: LMSType | None = None
    sso_tenant: str | None = None


class LMSClass(BaseModel):
    lms_id: int
    lms_type: LMSType
    lms_tenant: str
    name: str
    course_code: str
    term: str

    class Config:
        from_attributes = True


class LMSClasses(BaseModel):
    classes: list[LMSClass]

    class Config:
        from_attributes = True


class LMSClassRequest(BaseModel):
    name: str
    course_code: str
    term: str
    lms_id: int
    lms_type: LMSType
    lms_tenant: str

    class Config:
        from_attributes = True


class LMSUser(BaseModel, UserNameMixin):
    id: int

    class Config:
        from_attributes = True


class CanvasAccessToken(BaseModel):
    access_token: str
    expires_in: int
    refresh_token: str

    class Config:
        from_attributes = True


class CanvasStoredAccessToken(BaseModel):
    user_id: int
    access_token: str
    refresh_token: str
    expires_in: int
    token_added_at: datetime
    now: datetime

    class Config:
        from_attributes = True


class CanvasInitialAccessTokenRequest(BaseModel):
    client_id: str
    client_secret: str
    response_type: str
    code: str
    redirect_uri: str

    class Config:
        from_attributes = True


class CanvasRefreshAccessTokenRequest(BaseModel):
    client_id: str
    client_secret: str
    grant_type: str
    refresh_token: str

    class Config:
        from_attributes = True


T = TypeVar("T")


class CanvasRequestResponse(BaseModel, Generic[T]):
    response: list[dict[str, T]] | dict[str, T]
    next_page: str | None


class CreateUpdateCanvasClass(BaseModel):
    class_id: int
    user_id: int
    canvas_course: LMSClass

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
    private: bool | None = None
    lms_user: LMSUser | None = None
    lms_status: LMSStatus | None = None
    lms_class: LMSClass | None = None
    lms_last_synced: datetime | None = None
    any_can_create_assistant: bool | None = None
    any_can_publish_assistant: bool | None = None
    any_can_publish_thread: bool | None = None
    any_can_upload_class_file: bool | None = None
    download_link_expiration: str | None = None
    last_rate_limited_at: datetime | None = None

    class Config:
        from_attributes = True


class CreateClass(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    term: str = Field(..., min_length=1, max_length=100)
    api_key_id: int | None = None
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


class AIProvider(StrEnum):
    OPENAI = "openai"
    AZURE = "azure"


class APIKeyCheck(BaseModel):
    has_api_key: bool


class UpdateApiKey(BaseModel):
    api_key: str
    provider: AIProvider
    endpoint: str | None = None
    api_version: str | None = None

    class Config:
        from_attributes = True


class ApiKey(BaseModel):
    api_key: str
    provider: str
    endpoint: str | None = None
    api_version: str | None = None
    available_as_default: bool | None = None

    class Config:
        from_attributes = True


class APIKeyResponse(BaseModel):
    api_key: ApiKey | None = None

    class Config:
        from_attributes = True


class APIKeyModelResponse(BaseModel):
    api_key: str | None = None
    api_key_obj: ApiKey | None = None

    class Config:
        from_attributes = True


class DefaultAPIKey(BaseModel):
    id: int
    redacted_key: str
    name: str | None = None
    provider: str
    endpoint: str | None = None

    class Config:
        from_attributes = True


class DefaultAPIKeys(BaseModel):
    default_keys: list[DefaultAPIKey]

    class Config:
        from_attributes = True


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
        | Literal["incomplete"]
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
    attachments: dict[str, File] | None

    class Config:
        from_attributes = True


class AuthToken(BaseModel):
    """Auth Token - minimal token used to log in."""

    sub: str
    exp: int
    iat: int


class CanvasToken(BaseModel):
    """Canvas Token - minimal token used to sync class with Canvas course."""

    class_id: str
    user_id: str
    lms_tenant: str
    exp: int
    iat: int


class CanvasRedirect(BaseModel):
    url: str


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
