from datetime import date, datetime
from enum import Enum, StrEnum, auto
from typing import Any, Generic, Literal, NotRequired, TypeVar, Union
from typing_extensions import TypedDict, Annotated, TypeAlias

from openai._utils import PropertyInfo
from openai.types.beta.threads import (
    ImageFileContentBlock,
    TextContentBlock,
    RefusalContentBlock,
    ImageURLContentBlock,
)
from openai.types.beta.threads.text import Text as OpenAIText
from openai.types.beta.threads.annotation import (
    FileCitationAnnotation,
    FilePathAnnotation,
)
from openai.types.beta.assistant_tool import AssistantTool as Tool
from openai.types.beta.threads import Message as OpenAIMessage
from openai.types.responses.response_output_text import AnnotationURLCitation
from openai.types.responses.response_function_web_search import (
    Action as WebSearchAction,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)

from pingpong.authz.base import Relation
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


class ClassThreadCount(BaseModel):
    class_id: int
    class_name: str | None = None
    thread_count: int


class InstitutionClassThreadCountsResponse(BaseModel):
    institution_id: int
    classes: list[ClassThreadCount]


class ModelStatistics(BaseModel):
    model: str
    assistant_count: int


class ModelStatisticsResponse(BaseModel):
    statistics: list[ModelStatistics]


class RunDailyAssistantMessageModelStats(BaseModel):
    model: str | None
    total_runs: int
    runs_with_multiple_assistant_messages: int
    percentage: float


class RunDailyAssistantMessageAssistantStats(BaseModel):
    assistant_id: int | None
    assistant_name: str | None = None
    class_id: int | None = None
    class_name: str | None = None
    total_runs: int
    runs_with_multiple_assistant_messages: int
    percentage: float


class RunDailyAssistantMessageStats(BaseModel):
    date: date
    total_runs: int
    runs_with_multiple_assistant_messages: int
    percentage: float
    models: list[RunDailyAssistantMessageModelStats] | None = None
    assistants: list[RunDailyAssistantMessageAssistantStats] | None = None


class RunDailyAssistantMessageSummary(BaseModel):
    total_runs: int
    runs_with_multiple_assistant_messages: int
    percentage: float
    models: list[RunDailyAssistantMessageModelStats] | None = None
    assistants: list[RunDailyAssistantMessageAssistantStats] | None = None


class RunDailyAssistantMessageStatsResponse(BaseModel):
    statistics: list[RunDailyAssistantMessageStats]
    summary: RunDailyAssistantMessageSummary | None = None


class AssistantModelInfo(BaseModel):
    class_id: int
    class_name: str
    assistant_id: int
    assistant_name: str
    last_edited: datetime
    last_user_activity: datetime | None


class AssistantModelInfoResponse(BaseModel):
    model: str
    assistants: list[AssistantModelInfo]


class AssistantModelUpgradeRequest(BaseModel):
    deprecated_model: str
    replacement_model: str


class GenericStatus(BaseModel):
    status: str


class ManageAuthzRequest(BaseModel):
    grant: list[tuple[str, str, str]] = []
    revoke: list[tuple[str, str, str]] = []


class AuthzEntity(BaseModel):
    id: str | int | None = None
    type: str


class InspectAuthzTestResult(BaseModel):
    test: Literal["test"] = "test"
    verdict: bool


class InspectAuthzListResult(BaseModel):
    test: Literal["list"] = "list"
    list: list[int]


class InspectAuthzListResultPermissive(BaseModel):
    test: Literal["list"] = "list"
    list: list[int | str]


class InspectAuthzErrorResult(BaseModel):
    test: Literal["error"] = "error"
    error: str


InspectAuthzResult = Union[
    InspectAuthzTestResult,
    InspectAuthzListResult,
    InspectAuthzListResultPermissive,
    InspectAuthzErrorResult,
]


class InspectAuthz(BaseModel):
    subject: AuthzEntity
    relation: str
    object: AuthzEntity
    result: InspectAuthzResult


class InspectAuthzAllResult(BaseModel):
    result: list[Relation]


class AddEmailToUserRequest(BaseModel):
    current_email: str
    new_email: str


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
            image_url=get_gravatar_image(email) if email else "",
        )

    @classmethod
    def from_user(cls, user: "User") -> "Profile":
        """Return a profile from an email address and name."""
        hashed = get_email_hash(user.email) if user.email else ""
        name = (
            user.display_name
            if user.display_name
            else " ".join(filter(None, [user.first_name, user.last_name])) or user.email
        )
        return cls(
            name=name,
            email=user.email,
            gravatar_id=hashed,
            image_url=get_gravatar_image(user.email) if user.email else "",
        )


class UserState(Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    BANNED = "banned"


class UserNameMixin:
    email: str | None
    first_name: str | None
    last_name: str | None
    display_name: str | None

    @computed_field  # type: ignore
    @property
    def name(self) -> str | None:
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


class ExternalLoginProvider(BaseModel):
    id: int
    name: str
    display_name: str | None
    description: str | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class ExternalLoginProviders(BaseModel):
    providers: list[ExternalLoginProvider]

    model_config = ConfigDict(
        from_attributes=True,
    )


class ExternalLoginLookupItem(BaseModel):
    identifier: str = Field(..., min_length=1)
    provider: str | None = None
    provider_id: int | None = None

    @model_validator(mode="after")
    def _validate_provider_fields(self) -> "ExternalLoginLookupItem":
        has_provider = bool(self.provider and self.provider.strip())
        has_provider_id = self.provider_id is not None
        if not has_provider and not has_provider_id:
            raise ValueError("provider or provider_id is required")
        return self


class UpdateExternalLoginProvider(BaseModel):
    display_name: str | None
    description: str | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class ExternalLogin(BaseModel):
    id: int
    provider: str
    identifier: str
    provider_obj: ExternalLoginProvider

    model_config = ConfigDict(
        from_attributes=True,
    )


class ExternalLogins(BaseModel):
    user_id: int
    external_logins: list[ExternalLogin]


class User(BaseModel, UserNameMixin):
    id: int
    state: UserState
    created: datetime
    updated: datetime | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class File(BaseModel):
    id: int
    name: str
    content_type: str
    file_id: str
    vision_obj_id: int | None = None
    file_search_file_id: str | None = None
    code_interpreter_file_id: str | None = None
    vision_file_id: str | None = None
    private: bool | None
    uploader_id: int | None
    created: datetime
    updated: datetime | None
    image_description: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class Files(BaseModel):
    files: list[File]

    model_config = ConfigDict(
        from_attributes=True,
    )


class AssistantFiles(BaseModel):
    code_interpreter_files: list[File]
    file_search_files: list[File]

    model_config = ConfigDict(
        from_attributes=True,
    )


class AssistantFilesResponse(BaseModel):
    files: AssistantFiles

    model_config = ConfigDict(
        from_attributes=True,
    )


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

    model_config = ConfigDict(
        from_attributes=True,
    )


class VectorStoreDeleteResponse(BaseModel):
    vector_store_id: str
    deleted_file_ids: list[int]

    model_config = ConfigDict(
        from_attributes=True,
    )


class VectorStoreType(Enum):
    ASSISTANT = "assistant"
    THREAD = "thread"


class InteractionMode(StrEnum):
    CHAT = "chat"
    VOICE = "voice"


class AnonymousLink(BaseModel):
    id: int
    name: str | None
    share_token: str
    active: bool
    activated_at: datetime | None
    revoked_at: datetime | None


class AnonymousLinkResponse(BaseModel):
    link: AnonymousLink

    model_config = ConfigDict(
        from_attributes=True,
    )


class Assistant(BaseModel):
    id: int
    name: str
    version: int | None = None
    instructions: str
    description: str | None
    notes: str | None = None
    interaction_mode: InteractionMode
    tools: str
    model: str
    temperature: float | None
    verbosity: int | None
    reasoning_effort: int | None
    class_id: int
    creator_id: int
    locked: bool = False
    assistant_should_message_first: bool | None = None
    should_record_user_information: bool | None = None
    allow_user_file_uploads: bool | None = None
    allow_user_image_uploads: bool | None = None
    hide_reasoning_summaries: bool | None = None
    hide_file_search_result_quotes: bool | None = None
    hide_file_search_document_names: bool | None = None
    hide_file_search_queries: bool | None = None
    hide_web_search_sources: bool | None = None
    hide_web_search_actions: bool | None = None
    hide_mcp_server_call_details: bool | None = None
    use_latex: bool | None
    use_image_descriptions: bool | None
    hide_prompt: bool | None
    published: datetime | None
    endorsed: bool | None = None
    created: datetime
    updated: datetime | None
    share_links: list[AnonymousLink] | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


def temperature_validator(self):
    if (
        self.temperature is not None
        and self.interaction_mode == InteractionMode.VOICE
        and (self.temperature < 0.6 or self.temperature > 1.2)
    ):
        raise ValueError("Temperature must be between 0.6 and 1.2 for Voice mode.")
    return self


class ToolOption(TypedDict):
    type: (
        Literal["file_search"]
        | Literal["code_interpreter"]
        | Literal["web_search"]
        | Literal["mcp_server"]
    )


class MCPAuthType(StrEnum):
    NONE = "none"
    TOKEN = "token"
    HEADER = "header"


class MCPServerToolInput(BaseModel):
    """Input for create/update MCP servers - used in assistant requests"""

    display_name: str = Field(..., min_length=1, max_length=100)
    server_label: str | None = None
    server_url: HttpUrl = Field(..., max_length=2048)
    auth_type: MCPAuthType = MCPAuthType.NONE
    authorization_token: str | None = None
    headers: dict[str, str] | None = None
    description: str | None = Field(None, max_length=1000)
    enabled: bool = True

    @computed_field  # type: ignore
    @property
    def server_url_str(self) -> str:
        return str(self.server_url)


class MCPServerToolResponse(BaseModel):
    """Response model for MCP servers - uses server_label as identifier"""

    display_name: str
    server_label: str
    server_url: str
    auth_type: MCPAuthType
    headers: dict[str, str] | None = None
    description: str | None = None
    enabled: bool

    model_config = ConfigDict(
        from_attributes=True,
    )


class MCPServerToolsResponse(BaseModel):
    """Response model for list of MCP servers"""

    mcp_servers: list[MCPServerToolResponse]


class BufferedStreamHandlerToolCallState(BaseModel):
    tool_call_id: int
    output_index: int


class CreateAssistant(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    code_interpreter_file_ids: list[str] | None = None
    file_search_file_ids: list[str] | None = None
    instructions: str = Field(..., min_length=3)
    description: str
    notes: str | None = None
    interaction_mode: InteractionMode = InteractionMode.CHAT
    model: str = Field(..., min_length=2)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    reasoning_effort: int | None = Field(None, ge=-1, le=2)
    verbosity: int | None = Field(None, ge=0, le=2)
    tools: list[ToolOption] = Field(default_factory=list)
    published: bool = False
    use_latex: bool = False
    use_image_descriptions: bool = False
    hide_prompt: bool = False
    assistant_should_message_first: bool = False
    should_record_user_information: bool = False
    allow_user_file_uploads: bool = True
    allow_user_image_uploads: bool = True
    hide_reasoning_summaries: bool = True
    hide_file_search_result_quotes: bool = True
    hide_file_search_document_names: bool = False
    hide_file_search_queries: bool = True
    hide_web_search_sources: bool = False
    hide_web_search_actions: bool = False
    hide_mcp_server_call_details: bool = True
    deleted_private_files: list[int] = []
    create_classic_assistant: bool = False
    mcp_servers: list[MCPServerToolInput] = []

    _temperature_check = model_validator(mode="after")(temperature_validator)


class AssistantInstructionsPreviewRequest(BaseModel):
    instructions: str


class AssistantInstructionsPreviewResponse(BaseModel):
    instructions_preview: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class CopyAssistantRequest(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)
    target_class_id: int | None = None


class CopyAssistantCheckResponse(BaseModel):
    allowed: bool


class UpdateAssistantShareNameRequest(BaseModel):
    name: str


class UpdateAssistant(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)
    code_interpreter_file_ids: list[str] | None = None
    file_search_file_ids: list[str] | None = None
    instructions: str | None = Field(None, min_length=3)
    description: str | None = None
    notes: str | None = None
    interaction_mode: InteractionMode | None = None
    model: str | None = Field(None, min_length=2)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    reasoning_effort: int | None = Field(None, ge=-1, le=2)
    verbosity: int | None = Field(None, ge=0, le=2)
    tools: list[ToolOption] | None = None
    published: bool | None = None
    use_latex: bool | None = None
    hide_prompt: bool | None = None
    assistant_should_message_first: bool | None = None
    should_record_user_information: bool | None = None
    allow_user_file_uploads: bool | None = None
    allow_user_image_uploads: bool | None = None
    hide_reasoning_summaries: bool | None = None
    hide_file_search_result_quotes: bool | None = None
    hide_file_search_document_names: bool | None = None
    hide_file_search_queries: bool | None = None
    hide_web_search_sources: bool | None = None
    hide_web_search_actions: bool | None = None
    hide_mcp_server_call_details: bool | None = None
    use_image_descriptions: bool | None = None
    convert_to_next_gen: bool | None = None
    deleted_private_files: list[int] = []
    mcp_servers: list[MCPServerToolInput] | None = None

    _temperature_check = model_validator(mode="after")(temperature_validator)


class DeleteAssistant(BaseModel):
    has_code_interpreter_files: bool = False
    private_files: list[int] = []


class Assistants(BaseModel):
    assistants: list[Assistant]
    creators: dict[int, User]

    model_config = ConfigDict(
        from_attributes=True,
    )


class Thread(BaseModel):
    id: int
    name: str | None
    version: int = 2
    class_id: int
    interaction_mode: InteractionMode
    assistant_names: dict[int, str] = {}
    assistant_id: int | None = None
    private: bool
    tools_available: str | None
    user_names: list[str] = []
    created: datetime
    last_activity: datetime
    display_user_info: bool
    anonymous_session: bool = False
    is_current_user_participant: bool = False

    model_config = ConfigDict(
        from_attributes=True,
    )


class ThreadWithOptionalToken(BaseModel):
    thread: Thread
    session_token: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


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


class ImageProxy(BaseModel):
    name: str
    description: str
    content_type: str
    complements: str | None = None


class CreateThread(BaseModel):
    parties: list[int] = []
    message: str | None = None
    code_interpreter_file_ids: list[str] = Field([])
    file_search_file_ids: list[str] = Field([])
    vision_file_ids: list[str] = Field([])
    vision_image_descriptions: list[ImageProxy] = Field([])
    tools_available: list[ToolOption] = Field(default_factory=list)
    assistant_id: int
    timezone: str | None = None
    conversation_id: str | None = None

    _file_check = model_validator(mode="after")(file_validator)


class PromptRandomOption(BaseModel):
    id: str
    text: str
    weight: float = 1.0

    def __str__(self) -> str:
        return f"{repr(self.text)} (id={self.id}, weight={self.weight})"


class PromptRandomBlock(BaseModel):
    id: str
    seed: str
    options: list[PromptRandomOption] = []
    count: int = 1
    allow_repeat: bool = False
    sep: str = "\n"

    def __str__(self) -> str:
        options_str = ", ".join(str(option) for option in self.options)
        return f"PromptRandomBlock(id={self.id}, options=[{options_str}], count={self.count}, allow_repeat={self.allow_repeat}, seed={self.seed}, sep={repr(self.sep)})"


class CreateAudioThread(BaseModel):
    parties: list[int] = []
    assistant_id: int
    timezone: str | None = None
    conversation_id: str | None = None


class VideoMetadata(BaseModel):
    content_length: int
    content_type: str
    etag: str | None = None
    last_modified: datetime | None = None


class CreateThreadRunRequest(BaseModel):
    timezone: str | None = None


class ThreadName(BaseModel):
    name: str | None
    can_generate: bool


class ActivitySummaryOpts(BaseModel):
    days: int | None = 7


class ActivitySummarySubscription(BaseModel):
    class_id: int
    class_name: str
    class_private: bool
    class_has_api_key: bool
    subscribed: bool
    last_email_sent: datetime | None
    last_summary_empty: bool


class ExternalLoginsResponse(BaseModel):
    external_logins: list[ExternalLogin]


class ActivitySummarySubscriptionAdvancedOpts(BaseModel):
    dna_as_create: bool
    dna_as_join: bool


class ActivitySummarySubscriptions(BaseModel):
    subscriptions: list[ActivitySummarySubscription]
    advanced_opts: ActivitySummarySubscriptionAdvancedOpts


class AITopic(BaseModel):
    topic_label: str
    challenge: str
    confusion_example: str | None


class AITopicSummary(BaseModel):
    topic: AITopic
    relevant_threads: list[int]


class AIAssistantSummaryOutput(BaseModel):
    topics: list[AITopicSummary]


class AIAssistantSummary(BaseModel):
    assistant_name: str
    topics: list[AITopicSummary]
    has_threads: bool


class TopicSummary(BaseModel):
    topic_label: str
    challenge: str
    confusion_example: str | None
    relevant_thread_urls: list[str]


class AssistantSummary(BaseModel):
    assistant_name: str
    topics: list[TopicSummary]
    has_threads: bool


class ClassSummary(BaseModel):
    class_id: int
    class_name: str
    assistant_summaries: list[AssistantSummary]


class ClassSummaryExport(BaseModel):
    link: str
    summary_type: str | None
    title: str | None
    first_name: str
    email: str
    summary_html: str
    class_name: str
    time_since: str


class SummarySubscriptionResult(BaseModel):
    subscribed: bool


class ThreadUserMessages(BaseModel):
    id: int
    thread_id: str
    user_messages: list[str]


class ThreadsToSummarize(BaseModel):
    threads: list[ThreadUserMessages]


class NewThreadMessage(BaseModel):
    message: str = Field(..., min_length=1)
    code_interpreter_file_ids: list[str] = Field([])
    file_search_file_ids: list[str] = Field([])
    vision_file_ids: list[str] = Field([])
    vision_image_descriptions: list[ImageProxy] = Field([])
    timezone: str | None = None

    _file_check = model_validator(mode="after")(file_validator)


class Threads(BaseModel):
    threads: list[Thread]

    model_config = ConfigDict(
        from_attributes=True,
    )


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
    last_active: datetime | None = None
    roles: ClassUserRoles


class LMSType(Enum):
    CANVAS = "canvas"


class CreateUserResult(BaseModel):
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

    model_config = ConfigDict(
        from_attributes=True,
    )


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


class DownloadTranscriptExport(DownloadExport):
    thread_link: str
    thread_users: list[str]


class MessageForSpeakerMatch(BaseModel):
    role: str
    user_id: int | None
    text: str
    norm_text: str
    tokens: set[str]


class ClonedGroupNotification(BaseModel):
    link: str
    email: str = Field(..., min_length=3, max_length=100)
    class_name: str = Field(..., min_length=3, max_length=100)


class MultipleClassThreadExportRequest(BaseModel):
    class_ids: list[int]
    user_emails: list[str] | None = None
    user_ids: list[int] | None = None
    include_user_emails: bool = False


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

    model_config = ConfigDict(
        from_attributes=True,
    )


class CreateInstitution(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)


class UpdateInstitution(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)


class CopyInstitution(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)


class Institution(BaseModel):
    id: int
    name: str
    description: str | None
    logo: str | None
    default_api_key_id: int | None = None
    created: datetime
    updated: datetime | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class Institutions(BaseModel):
    institutions: list[Institution]

    model_config = ConfigDict(
        from_attributes=True,
    )


class AddInstitutionAdminRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=100)


class InstitutionAdmin(BaseModel, UserNameMixin):
    id: int

    model_config = ConfigDict(
        from_attributes=True,
    )


class InstitutionWithAdmins(Institution):
    admins: list[InstitutionAdmin] = Field(default_factory=list)
    root_admins: list[InstitutionAdmin] = Field(default_factory=list)

    model_config = ConfigDict(
        from_attributes=True,
    )


class InstitutionAdminResponse(BaseModel):
    institution_id: int
    user_id: int
    email: str
    added_admin: bool


class LMSPlatform(StrEnum):
    CANVAS = "canvas"


class LTIRegistrationReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LTITokenAlgorithm(StrEnum):
    RS256 = "RS256"


class LTIRegistrationInstitution(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class LTIRegistrationReviewer(BaseModel):
    id: int
    email: str | None
    first_name: str | None
    last_name: str | None
    display_name: str | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class LTIRegistration(BaseModel):
    id: int
    issuer: str
    client_id: str | None
    auth_login_url: str
    auth_token_url: str
    key_set_url: str
    token_algorithm: LTITokenAlgorithm
    lms_platform: LMSPlatform | None
    canvas_account_name: str | None
    admin_name: str | None
    admin_email: str | None
    friendly_name: str | None
    enabled: bool
    review_status: LTIRegistrationReviewStatus
    internal_notes: str | None
    review_notes: str | None
    review_by: LTIRegistrationReviewer | None
    institutions: list[LTIRegistrationInstitution]
    created: datetime
    updated: datetime | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class LTIRegistrations(BaseModel):
    registrations: list[LTIRegistration]

    model_config = ConfigDict(
        from_attributes=True,
    )


class LTIRegistrationDetail(LTIRegistration):
    openid_configuration: str | None
    registration_data: str | None
    lti_classes_count: int = 0

    model_config = ConfigDict(
        from_attributes=True,
    )


class UpdateLTIRegistration(BaseModel):
    friendly_name: str | None = Field(None, max_length=200)
    admin_name: str | None = Field(None, max_length=200)
    admin_email: str | None = Field(None, max_length=200)
    internal_notes: str | None = Field(None, max_length=5000)
    review_notes: str | None = Field(None, max_length=5000)


class SetLTIRegistrationStatus(BaseModel):
    review_status: LTIRegistrationReviewStatus


class SetLTIRegistrationEnabled(BaseModel):
    enabled: bool


class SetLTIRegistrationInstitutions(BaseModel):
    institution_ids: list[int]


class InstitutionWithDefaultAPIKey(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class InstitutionsWithDefaultAPIKey(BaseModel):
    institutions: list[InstitutionWithDefaultAPIKey]

    model_config = ConfigDict(
        from_attributes=True,
    )


class SetInstitutionDefaultAPIKeyRequest(BaseModel):
    default_api_key_id: int | None = None


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


class LTIStatus(StrEnum):
    PENDING = auto()
    LINKED = auto()
    ERROR = auto()


class LMSInstance(BaseModel):
    tenant: str
    tenant_friendly_name: str
    type: LMSType
    base_url: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class LMSInstances(BaseModel):
    instances: list[LMSInstance]

    model_config = ConfigDict(
        from_attributes=True,
    )


class CreateUserClassRoles(BaseModel):
    roles: list[CreateUserClassRole]
    silent: bool = False
    lms_tenant: str | None = None
    lms_type: LMSType | None = None
    lti_class_id: int | None = None
    is_lti_launch: bool = False
    sso_tenant: str | None = None


class LTIClass(BaseModel):
    id: int
    canvas_account_name: str | None = None
    client_id: str | None = None
    lti_status: LTIStatus
    lti_platform: LMSPlatform
    registration_id: int
    course_name: str | None = None
    course_term: str | None = None
    course_id: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class LTIClasses(BaseModel):
    classes: list[LTIClass]

    model_config = ConfigDict(
        from_attributes=True,
    )


class LMSClass(BaseModel):
    lms_id: int
    lms_type: LMSType
    lms_tenant: str
    name: str
    course_code: str
    term: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class LMSClasses(BaseModel):
    classes: list[LMSClass]

    model_config = ConfigDict(
        from_attributes=True,
    )


class LMSClassRequest(BaseModel):
    name: str
    course_code: str
    term: str
    lms_id: int
    lms_type: LMSType
    lms_tenant: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class LMSUser(BaseModel, UserNameMixin):
    id: int

    model_config = ConfigDict(
        from_attributes=True,
    )


class CanvasAccessToken(BaseModel):
    access_token: str
    expires_in: int
    refresh_token: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class CanvasStoredAccessToken(BaseModel):
    user_id: int | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    token_added_at: datetime | None = None
    now: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


class CanvasInitialAccessTokenRequest(BaseModel):
    client_id: str
    client_secret: str
    response_type: str
    code: str
    redirect_uri: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class CanvasRefreshAccessTokenRequest(BaseModel):
    client_id: str
    client_secret: str
    grant_type: str
    refresh_token: str

    model_config = ConfigDict(
        from_attributes=True,
    )


T = TypeVar("T")


class CanvasRequestResponse(BaseModel, Generic[T]):
    response: list[dict[str, T]] | dict[str, T]
    next_page: str | None


class CreateUpdateCanvasClass(BaseModel):
    class_id: int
    user_id: int
    canvas_course: LMSClass

    model_config = ConfigDict(
        from_attributes=True,
    )


class AIProvider(StrEnum):
    OPENAI = "openai"
    AZURE = "azure"


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
    lms_type: LMSType | None = None
    lms_tenant: str | None = None
    lms_status: LMSStatus | None = None
    lms_class: LMSClass | None = None
    lms_last_synced: datetime | None = None
    any_can_create_assistant: bool | None = None
    any_can_publish_assistant: bool | None = None
    any_can_share_assistant: bool | None = None
    any_can_publish_thread: bool | None = None
    any_can_upload_class_file: bool | None = None
    download_link_expiration: str | None = None
    last_rate_limited_at: datetime | None = None
    ai_provider: AIProvider | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class ClassLMSInfo(BaseModel):
    id: int
    name: str
    created: datetime
    updated: datetime | None
    private: bool | None = None
    lms_user: LMSUser | None = None
    lms_type: LMSType | None = None
    lms_tenant: str | None = None
    lms_status: LMSStatus | None = None
    lms_class: LMSClass | None = None
    lms_course_id: int | None = None
    lms_access_token: SecretStr | None = None
    lms_refresh_token: SecretStr | None = None
    lms_expires_in: int | None = None
    lms_token_added_at: datetime | None = None
    lms_last_synced: datetime | None = None


class CopyClassRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    term: str = Field(..., min_length=1, max_length=100)
    institution_id: int | None = None
    private: bool = False
    any_can_create_assistant: bool = False
    any_can_publish_assistant: bool = False
    any_can_share_assistant: bool = False
    any_can_publish_thread: bool = False
    any_can_upload_class_file: bool = False
    copy_assistants: Literal["moderators", "all"] = "moderators"
    copy_users: Literal["moderators", "all"] = "moderators"


class CreateClass(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    term: str = Field(..., min_length=1, max_length=100)
    api_key_id: int | None = None
    private: bool = False
    any_can_create_assistant: bool = False
    any_can_publish_assistant: bool = False
    any_can_share_assistant: bool = False
    any_can_publish_thread: bool = False
    any_can_upload_class_file: bool = False


class UpdateClass(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=100)
    term: str | None = Field(None, min_length=1, max_length=100)
    private: bool | None = None
    any_can_create_assistant: bool | None = None
    any_can_publish_assistant: bool | None = None
    any_can_share_assistant: bool | None = None
    any_can_publish_thread: bool | None = None
    any_can_upload_class_file: bool | None = None


class TransferClassRequest(BaseModel):
    institution_id: int = Field(..., gt=0)


class APIKeyCheck(BaseModel):
    has_api_key: bool


class UpdateApiKey(BaseModel):
    api_key: str
    provider: AIProvider
    endpoint: str | None = None
    api_version: str | None = None

    @field_validator("api_key", "endpoint", "api_version")
    @classmethod
    def strip_if_not_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip()
        return v

    model_config = ConfigDict(
        from_attributes=True,
    )


class ApiKey(BaseModel):
    api_key: str
    provider: str
    endpoint: str | None = None
    api_version: str | None = None
    available_as_default: bool | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class APIKeyValidationResponse(BaseModel):
    valid: bool
    region: str | None = None


class APIKeyResponse(BaseModel):
    api_key: ApiKey | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class APIKeyModelResponse(BaseModel):
    api_key: str | None = None
    api_key_obj: ApiKey | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class DefaultAPIKey(BaseModel):
    id: int
    redacted_key: str
    name: str | None = None
    provider: str
    endpoint: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class DefaultAPIKeys(BaseModel):
    default_keys: list[DefaultAPIKey]

    model_config = ConfigDict(
        from_attributes=True,
    )


class AssistantModel(BaseModel):
    id: str
    created: datetime
    owner: str
    name: str
    description: str
    default_prompt_id: str | None = None
    type: InteractionMode
    is_latest: bool
    is_new: bool
    highlight: bool
    supports_classic_assistants: bool
    supports_next_gen_assistants: bool
    supports_minimal_reasoning_effort: bool
    supports_none_reasoning_effort: bool
    supports_verbosity: bool
    supports_web_search: bool
    supports_mcp_server: bool
    supports_vision: bool
    vision_support_override: bool | None = None
    supports_file_search: bool
    supports_code_interpreter: bool
    supports_temperature: bool
    supports_reasoning: bool
    hide_in_model_selector: bool | None = None
    reasoning_effort_levels: list[int] | None = None


class AssistantModelLite(BaseModel):
    id: str
    supports_vision: bool
    azure_supports_vision: bool = False  # For future use
    supports_reasoning: bool = False


class AssistantModelLiteResponse(BaseModel):
    models: list[AssistantModelLite]

    model_config = ConfigDict(
        from_attributes=True,
    )


class AssistantModelDict(TypedDict):
    name: str
    sort_order: float
    is_latest: bool
    is_new: bool
    highlight: bool
    type: Literal["chat", "voice"]
    supports_classic_assistants: bool
    supports_next_gen_assistants: bool
    supports_minimal_reasoning_effort: bool
    supports_none_reasoning_effort: bool
    supports_verbosity: bool
    supports_web_search: bool
    supports_mcp_server: bool
    supports_vision: bool
    supports_file_search: bool
    supports_code_interpreter: bool
    supports_temperature: bool
    supports_reasoning: bool
    description: str
    reasoning_effort_levels: NotRequired[list[int]]
    default_prompt_id: NotRequired[str]


class AssistantDefaultPrompt(BaseModel):
    id: str
    prompt: str


class AssistantModels(BaseModel):
    models: list[AssistantModel]
    default_prompts: list[AssistantDefaultPrompt] = []
    enforce_classic_assistants: bool = False


class Classes(BaseModel):
    classes: list[Class]

    model_config = ConfigDict(
        from_attributes=True,
    )


class OpenAIRunError(BaseModel):
    code: str
    message: str


class OpenAIRun(BaseModel):
    # See OpenAI's Run type. We select a subset of fields.
    id: str
    assistant_id: str
    cancelled_at: int | None
    completed_at: int | None
    created_at: float
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
        | Literal["pending"]
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


class MessageContentCodeOutputImageURL(BaseModel):
    url: str
    type: Literal["code_output_image_url"]


class MessageContentCodeOutputLogs(BaseModel):
    logs: str
    type: Literal["code_output_logs"]


class MessageContentCode(BaseModel):
    code: str
    type: Literal["code"]


CodeInterpreterMessageContent = Union[
    MessageContentCodeOutputImageFile,
    MessageContentCode,
    MessageContentCodeOutputImageURL,
    MessageContentCodeOutputLogs,
]


class CodeInterpreterPlaceholderContent(BaseModel):
    run_id: str
    step_id: str
    thread_id: str
    type: Literal["code_interpreter_call_placeholder"]


class FileSearchCall(BaseModel):
    step_id: str
    type: Literal["file_search_call"]
    queries: list[str]
    status: Literal["in_progress", "searching", "completed", "incomplete", "failed"]


class FileSearchMessage(BaseModel):
    id: str
    assistant_id: str
    created_at: float
    content: list[FileSearchCall]
    metadata: dict[str, str]
    object: Literal["thread.message"]
    message_type: Literal["file_search_call"]
    role: Literal["assistant"]
    run_id: str
    thread_id: str
    output_index: int | None = None


class WebSearchActionType(StrEnum):
    SEARCH = "search"
    FIND = "find"
    OPEN_PAGE = "open_page"


class WebSearchCall(BaseModel):
    step_id: str
    type: Literal["web_search_call"]
    action: WebSearchAction | None = None
    status: Literal["in_progress", "searching", "completed", "incomplete", "failed"]


class WebSearchMessage(BaseModel):
    id: str
    assistant_id: str
    created_at: float
    content: list[WebSearchCall]
    metadata: dict[str, str]
    object: Literal["thread.message"]
    message_type: Literal["web_search_call"]
    role: Literal["assistant"]
    run_id: str
    thread_id: str
    output_index: int | None = None


class MCPListToolsTool(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None


class MCPServerCall(BaseModel):
    step_id: str
    type: Literal["mcp_server_call"]
    server_label: str
    server_name: str | None = None
    tool_name: str | None = None
    arguments: str | None = None
    output: str | None = None
    error: dict[str, Any] | str | None = None
    status: (
        Literal[
            "in_progress",
            "completed",
            "incomplete",
            "calling",
            "failed",
        ]
        | None
    ) = None


class MCPListToolsCall(BaseModel):
    step_id: str
    type: Literal["mcp_list_tools_call"]
    server_label: str
    server_name: str | None = None
    tools: list[MCPListToolsTool] = []
    error: dict[str, Any] | str | None = None
    status: (
        Literal[
            "in_progress",
            "completed",
            "incomplete",
            "calling",
            "failed",
        ]
        | None
    ) = None


class MCPMessage(BaseModel):
    id: str
    assistant_id: str
    created_at: float
    content: list[MCPServerCall | MCPListToolsCall]
    metadata: dict[str, str]
    object: Literal["thread.message"]
    message_type: Literal["mcp_server_call", "mcp_list_tools_call"]
    role: Literal["assistant"]
    run_id: str
    thread_id: str
    output_index: int | None = None


class CodeInterpreterMessage(BaseModel):
    id: str
    assistant_id: str
    created_at: float
    content: (
        list[CodeInterpreterMessageContent] | list[CodeInterpreterPlaceholderContent]
    )
    metadata: dict[str, str]
    object: Literal["thread.message"] | Literal["code_interpreter_call_placeholder"]
    message_type: Literal["code_interpreter_call"] | None = None
    role: Literal["assistant"]
    run_id: str
    thread_id: str
    output_index: int | None = None


class CodeInterpreterMessages(BaseModel):
    ci_messages: list[CodeInterpreterMessage] = []


class ThreadRun(BaseModel):
    thread: Thread
    run: OpenAIRun | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class ThreadParticipants(BaseModel):
    user: list[str]
    assistant: dict[int, str]


ThreadAnnotation: TypeAlias = Annotated[
    Union[FileCitationAnnotation, FilePathAnnotation, AnnotationURLCitation],
    PropertyInfo(discriminator="type"),
]


class ThreadText(OpenAIText):
    annotations: list[ThreadAnnotation]


class ThreadTextContentBlock(TextContentBlock):
    text: ThreadText


ThreadMessageContent: TypeAlias = Annotated[
    Union[
        ImageFileContentBlock,
        ImageURLContentBlock,
        ThreadTextContentBlock,
        RefusalContentBlock,
    ],
    PropertyInfo(discriminator="type"),
]


class ThreadMessage(OpenAIMessage):
    status: Literal["in_progress", "incomplete", "completed"] | None
    """
    The status of the message, which can be either `in_progress`, `incomplete`, or
    `completed`. Can be `None` for user messages.
    """

    created_at: float | int
    """Classic Assistants:
    The Unix timestamp (in seconds) for when the message was created.

    Next-Gen Assistants:
    The Unix timestamp (in fractional seconds) for when the message was created."""

    output_index: int | None = None
    """The output index of the message, if applicable for Next-Gen Assistants."""

    content: list[ThreadMessageContent]
    """The content of the message in array of text and/or images."""

    metadata: dict[str, str | bool] | None = None
    """Set of 16 key-value pairs that can be attached to an object.

    This can be useful for storing additional information about the object in a
    structured format, and querying for objects via API or the dashboard.

    Keys are strings with a maximum length of 64 characters. Values are strings with
    a maximum length of 512 characters.

    **Departure from OpenAI API:** This field can also include boolean values, in addition
    to strings.
    """


class ThreadMessages(BaseModel):
    limit: int
    messages: list[ThreadMessage]
    fs_messages: list[FileSearchMessage] = []
    ci_messages: list[CodeInterpreterMessage] = []
    ws_messages: list[WebSearchMessage] = []
    mcp_messages: list[MCPMessage] = []
    reasoning_messages: list["ReasoningMessage"] = []
    has_more: bool


class VoiceModeRecording(BaseModel):
    recording_id: str
    duration: int

    model_config = ConfigDict(
        from_attributes=True,
    )


class ThreadWithMeta(BaseModel):
    thread: Thread
    model: str
    tools_available: str
    run: OpenAIRun | None
    messages: list[ThreadMessage]
    limit: int
    ci_messages: list[CodeInterpreterMessage] | None
    fs_messages: list[FileSearchMessage] | None = None
    ws_messages: list[WebSearchMessage] | None = None
    mcp_messages: list[MCPMessage] | None = None
    reasoning_messages: list["ReasoningMessage"] | None = None
    attachments: dict[str, File] | None
    instructions: str | None
    recording: VoiceModeRecording | None = None
    has_more: bool

    model_config = ConfigDict(
        from_attributes=True,
    )


class FileSearchToolAnnotationResult(BaseModel):
    file_id: str
    filename: str
    text: str


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
    ANONYMOUS = auto()
    MISSING = auto()
    INVALID = auto()
    ERROR = auto()


class SessionState(BaseModel):
    status: SessionStatus
    error: str | None = None
    token: SessionToken | None = None
    user: User | None = None
    profile: Profile | None = None
    agreement_id: int | None = None


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


class AgreementBody(BaseModel):
    id: int
    body: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class Agreement(BaseModel):
    id: int
    name: str
    created: datetime
    updated: datetime | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class Agreements(BaseModel):
    agreements: list[Agreement]

    model_config = ConfigDict(
        from_attributes=True,
    )


class AgreementPolicyLite(BaseModel):
    id: int

    model_config = ConfigDict(
        from_attributes=True,
    )


class AgreementDetail(BaseModel):
    id: int
    name: str
    body: str
    policies: list[AgreementPolicyLite]

    model_config = ConfigDict(
        from_attributes=True,
    )


class AgreementLite(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(
        from_attributes=True,
    )


class AgreementPolicy(BaseModel):
    id: int
    name: str
    agreement_id: int
    agreement: AgreementLite
    not_before: datetime | None
    not_after: datetime | None
    apply_to_all: bool

    model_config = ConfigDict(
        from_attributes=True,
    )


class ExternalLoginProviderLite(BaseModel):
    id: int

    model_config = ConfigDict(
        from_attributes=True,
    )


class AgreementPolicyDetail(BaseModel):
    id: int
    name: str
    agreement_id: int
    not_before: datetime | None
    not_after: datetime | None
    apply_to_all: bool
    limit_to_providers: list[ExternalLoginProviderLite] | None

    model_config = ConfigDict(
        from_attributes=True,
    )


class AgreementPolicies(BaseModel):
    policies: list[AgreementPolicy]

    model_config = ConfigDict(
        from_attributes=True,
    )


class CreateAgreementRequest(BaseModel):
    name: str
    body: str


class UpdateAgreementRequest(BaseModel):
    name: str | None = None
    body: str | None = None


class ToggleAgreementPolicyRequest(BaseModel):
    action: Literal["enable", "disable"]


class CreateAgreementPolicyRequest(BaseModel):
    name: str
    agreement_id: int
    apply_to_all: bool
    limit_to_providers: list[int] | None


class UpdateAgreementPolicyRequest(BaseModel):
    name: str | None = None
    agreement_id: int | None = None
    apply_to_all: bool | None = None
    limit_to_providers: list[int] | None = None


class AnnotationType(StrEnum):
    FILE_PATH = "file_path"
    URL_CITATION = "url_citation"
    FILE_CITATION = "file_citation"
    CONTAINER_FILE_CITATION = "container_file_citation"


class CodeInterpreterOutputType(StrEnum):
    LOGS = "logs"
    IMAGE = "image"


class ToolCallType(StrEnum):
    CODE_INTERPRETER = "code_interpreter_call"
    FILE_SEARCH = "file_search_call"
    WEB_SEARCH = "web_search_call"
    MCP_SERVER = "mcp_server_call"
    MCP_LIST_TOOLS = "mcp_list_tools_call"


class ToolCallStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SEARCHING = "searching"
    INTERPRETING = "interpreting"
    CALLING = "calling"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class MessagePartType(StrEnum):
    INPUT_TEXT = "input_text"
    INPUT_IMAGE = "input_image"
    OUTPUT_TEXT = "output_text"
    REFUSAL = "refusal"


class MessageStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    PENDING = "pending"


class ReasoningStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"


class ReasoningSummaryPart(BaseModel):
    id: int
    part_index: int
    summary_text: str


class ReasoningCall(BaseModel):
    step_id: str
    type: Literal["reasoning"]
    summary: list[ReasoningSummaryPart]
    status: ReasoningStatus
    thought_for: str | None = None


class ReasoningMessage(BaseModel):
    id: str
    assistant_id: str
    created_at: float
    content: list[ReasoningCall]
    metadata: dict[str, str]
    object: Literal["thread.message"]
    message_type: Literal["reasoning"]
    role: Literal["assistant"]
    run_id: str
    thread_id: str
    output_index: int | None = None


class MessageRole(StrEnum):
    USER = "user"
    SYSTEM = "system"
    ASSISTANT = "assistant"
    DEVELOPER = "developer"


class RunStatus(StrEnum):
    QUEUED = "queued"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
