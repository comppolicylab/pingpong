from openai.types.beta.assistant_create_params import Tool
from openai.types.beta.threads import Run as OpenAIRun
from openai.types.beta.threads import ThreadMessage as OpenAIMessage
from pydantic import BaseModel, SecretStr

from .gravatar import get_email_hash, get_gravatar_image


class GenericStatus(BaseModel):
    status: str


class File(BaseModel):
    id: int
    name: str
    content_type: str
    file_id: str
    class_id: int
    created: str
    updated: str | None

    class Config:
        orm_mode = True


class Files(BaseModel):
    files: list[File]

    class Config:
        orm_mode = True


class Assistant(BaseModel):
    id: int
    name: str
    instructions: str
    tools: str
    model: str
    class_id: int
    creator_id: int
    files: list[File]
    published: str | None
    created: str
    updated: str | None

    class Config:
        orm_mode = True


class CreateAssistant(BaseModel):
    name: str
    file_ids: list[str]
    instructions: str
    model: str
    tools: list[Tool]


class Assistants(BaseModel):
    my_assistants: list[Assistant]
    class_assistants: list[Assistant]

    class Config:
        orm_mode = True


class Thread(BaseModel):
    id: int
    name: str
    thread_id: str
    class_id: int
    assistant_id: int
    private: bool
    users: list["User"]
    created: str
    updated: str | None

    class Config:
        orm_mode = True


class CreateThread(BaseModel):
    parties: list[str]
    message: str
    assistant_id: int


class Threads(BaseModel):
    threads: list[Thread]

    class Config:
        orm_mode = True


class User(BaseModel):
    id: int
    name: str
    email: str
    state: str
    classes: list["Class"]
    institutions: list["Institution"]
    super_admin: bool
    threads: list[Thread]
    created: str
    updated: str | None

    class Config:
        orm_mode = True


class Institution(BaseModel):
    id: int
    name: str
    description: str | None
    logo: str | None
    created: str
    updated: str | None

    class Config:
        orm_mode = True


class Institutions(BaseModel):
    institutions: list[Institution]

    class Config:
        orm_mode = True


class Class(BaseModel):
    id: int
    name: str
    term: str
    institution_id: int
    assistants: list[Assistant]
    threads: list[Thread]
    users: list[User]
    created: str
    updated: str | None
    api_key: SecretStr | None

    class Config:
        orm_mode = True


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
        orm_mode = True


class ThreadRun(BaseModel):
    thread: Thread
    run: OpenAIRun | None

    class Config:
        orm_mode = True


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


class ThreadWithMeta(BaseModel):
    thread: Thread
    hash: str
    run: OpenAIRun | None
    messages: list[OpenAIMessage]
    participants: dict[str, Profile]

    class Config:
        orm_mode = True
