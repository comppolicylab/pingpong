import json
from datetime import datetime
from typing import AsyncGenerator, List, Optional

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    and_,
    delete,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgres_upsert
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    joinedload,
    mapped_column,
    relationship,
)
from sqlalchemy.sql import func
import pingpong.schemas as schemas


def _get_upsert_stmt(session: AsyncSession):
    """Get the appropriate upsert statement for the current database."""
    dialect = session.bind.dialect.name
    match dialect:
        case "postgresql":
            return postgres_upsert
        case "sqlite":
            return sqlite_upsert
        case _:
            raise NotImplementedError(f"Upsert not implemented for {dialect}")


class Base(AsyncAttrs, DeclarativeBase):
    pass


class UserClassRole(Base):
    __tablename__ = "users_classes"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, primary_key=True
    )
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id"), nullable=False, primary_key=True
    )
    role = Column(SQLEnum(schemas.Role), nullable=True)
    title: Mapped[Optional[str]]
    user = relationship("User", back_populates="classes")
    class_ = relationship("Class", back_populates="users")

    @classmethod
    async def get(
        cls, session: AsyncSession, user_id: int, class_id: int
    ) -> Optional["UserClassRole"]:
        stmt = select(UserClassRole).where(
            and_(
                UserClassRole.user_id == int(user_id),
                UserClassRole.class_id == int(class_id),
            )
        )
        return await session.scalar(stmt)

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        user_id: int,
        class_id: int,
    ) -> "UserClassRole":
        stmt = (
            _get_upsert_stmt(session)(UserClassRole)
            .values(
                user_id=int(user_id),
                class_id=int(class_id),
            )
            .on_conflict_do_nothing(
                index_elements=[UserClassRole.user_id, UserClassRole.class_id],
            )
            .returning(UserClassRole)
        )
        return await session.scalar(stmt)

    @classmethod
    async def delete(cls, session: AsyncSession, user_id: int, class_id: int) -> None:
        stmt = delete(UserClassRole).where(
            and_(
                UserClassRole.user_id == int(user_id),
                UserClassRole.class_id == int(class_id),
            )
        )
        await session.execute(stmt)
        return None


class UserInstitutionRole(Base):
    __tablename__ = "users_institutions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, primary_key=True
    )
    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id"), nullable=False, primary_key=True
    )
    role = Column(SQLEnum(schemas.Role), nullable=True)
    title: Mapped[Optional[str]]
    user = relationship("User", back_populates="institutions")
    institution = relationship("Institution", back_populates="users")


user_thread_association = Table(
    "users_threads",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("thread_id", Integer, ForeignKey("threads.id")),
    Index("user_thread_idx", "user_id", "thread_id", unique=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Name column is deprecated - use first_name and last_name instead
    _name = Column("name", String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    email = Column(String, unique=True)
    state = Column(SQLEnum(schemas.UserState), default=schemas.UserState.UNVERIFIED)
    classes: Mapped[List["UserClassRole"]] = relationship(
        back_populates="user", lazy="selectin"
    )
    institutions: Mapped[List["UserInstitutionRole"]] = relationship(
        back_populates="user", lazy="selectin"
    )
    assistants: Mapped[List["Assistant"]] = relationship(
        "Assistant", back_populates="creator"
    )
    super_admin = Column(Boolean, default=False)
    threads = relationship(
        "Thread", secondary=user_thread_association, back_populates="users"
    )
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    async def verify(self, session: AsyncSession) -> None:
        self.state = schemas.UserState.VERIFIED
        session.add(self)

    @classmethod
    async def update_info(
        self, session: AsyncSession, user_id: int, data: schemas.UpdateUserInfo
    ) -> "User":
        data_dict = data.model_dump(exclude_none=True)
        stmt = update(User).where(User.id == int(user_id)).values(**data_dict)
        await session.execute(stmt)
        return await User.get_by_id(session, user_id)

    @classmethod
    async def get_by_email(cls, session: AsyncSession, email: str) -> "User":
        stmt = select(User).where(func.lower(User.email) == func.lower(email))
        return await session.scalar(stmt)

    @classmethod
    async def get_or_create_by_email(
        cls,
        session: AsyncSession,
        email: str,
        initial_state: schemas.UserState = schemas.UserState.UNVERIFIED,
    ) -> "User":
        existing = await cls.get_by_email(session, email)
        if existing:
            return existing
        user = User(email=email, state=initial_state)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "User":
        stmt = select(User).where(User.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_all_by_id(cls, session: AsyncSession, ids: List[int]) -> List["User"]:
        if not ids:
            return []
        stmt = select(User).where(User.id.in_([int(id_) for id_ in ids]))
        result = await session.execute(stmt)
        return [row.User for row in result]


class Institution(Base):
    __tablename__ = "institutions"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    description = Column(String, nullable=True)
    logo = Column(String, nullable=True)
    classes = relationship("Class", back_populates="institution")
    users: Mapped[List["UserInstitutionRole"]] = relationship(
        "UserInstitutionRole", back_populates="institution"
    )
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def create(
        cls, session: AsyncSession, data: schemas.CreateInstitution
    ) -> "Institution":
        institution = Institution(**data.dict())
        session.add(institution)
        await session.flush()
        await session.refresh(institution)
        return institution

    @classmethod
    async def get_all_by_id(
        cls, session: AsyncSession, ids: list[int]
    ) -> List["Institution"]:
        if not ids:
            return []
        stmt = select(Institution).where(Institution.id.in_(ids))
        result = await session.execute(stmt)
        return [row.Institution for row in result]

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Institution":
        stmt = select(Institution).where(Institution.id == int(id_))
        return await session.scalar(stmt)


file_assistant_association = Table(
    "files_assistants",
    Base.metadata,
    Column("file_id", Integer, ForeignKey("files.id")),
    Column("assistant_id", Integer, ForeignKey("assistants.id")),
    Index("file_assistant_idx", "file_id", "assistant_id", unique=True),
)

code_interpreter_file_assistant_association = Table(
    "code_interpreter_files_assistants",
    Base.metadata,
    Column("file_id", Integer, ForeignKey("files.id")),
    Column("assistant_id", Integer, ForeignKey("assistants.id")),
    Index(
        "code_interpreter_file_assistant_idx", "file_id", "assistant_id", unique=True
    ),
)

code_interpreter_file_thread_association = Table(
    "code_interpreter_files_threads",
    Base.metadata,
    Column("file_id", Integer, ForeignKey("files.id")),
    Column("thread_id", Integer, ForeignKey("threads.id")),
    Index("code_interpreter_file_thread_idx", "file_id", "thread_id", unique=True),
)

file_vector_store_association = Table(
    "file_vector_stores",
    Base.metadata,
    Column("file_id", Integer, ForeignKey("files.id")),
    Column("vector_store_id", Integer, ForeignKey("vector_stores.id")),
    Index("file_vector_store_idx", "file_id", "vector_store_id", unique=True),
)


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    content_type = Column(String)
    file_id = Column(String)
    class_id = Column(Integer, ForeignKey("classes.id"))
    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=True, default=None)
    private = Column(Boolean, default=False)
    class_ = relationship("Class", back_populates="files")
    assistants = relationship(
        "Assistant",
        secondary=file_assistant_association,
        back_populates="files",
    )
    assistants_v2 = relationship(
        "Assistant",
        secondary=code_interpreter_file_assistant_association,
        back_populates="code_interpreter_files",
    )
    vector_stores = relationship(
        "VectorStore", secondary=file_vector_store_association, back_populates="files"
    )
    threads = relationship(
        "Thread",
        secondary=code_interpreter_file_thread_association,
        back_populates="code_interpreter_files",
    )

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "File":
        file = File(**data)
        session.add(file)
        await session.flush()
        await session.refresh(file)
        return file

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "File":
        stmt = select(File).where(File.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def delete(cls, session: AsyncSession, id_: int) -> None:
        stmt = delete(File).where(File.id == int(id_))
        await session.execute(stmt)

    @classmethod
    async def get_all_by_id(cls, session: AsyncSession, ids: list[int]) -> list["File"]:
        if not ids:
            return []
        stmt = select(File).where(File.id.in_(ids))
        result = await session.execute(stmt)
        return [row.File for row in result]

    @classmethod
    async def get_all_by_file_id(
        cls, session: AsyncSession, ids: List[str]
    ) -> List["File"]:
        if not ids:
            return []
        stmt = select(File).where(File.file_id.in_(ids))
        result = await session.execute(stmt)
        return [row.File for row in result]

    @classmethod
    async def get_object_ids_by_file_id(
        cls, session: AsyncSession, ids: List[str]
    ) -> List[int]:
        if not ids:
            return []
        stmt = select(File.id).where(File.file_id.in_(ids))
        result = await session.execute(stmt)
        return [row[0] for row in result]

    @classmethod
    async def get_id_tuple_by_file_id(
        cls, session: AsyncSession, ids: List[str]
    ) -> AsyncGenerator[tuple[str, int], None]:
        stmt = select(File.file_id, File.id).where(File.file_id.in_(ids))
        result = await session.execute(stmt)
        for row in result:
            yield row


class VectorStore(Base):
    __tablename__ = "vector_stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    version = Column(Integer, default=2)
    vector_store_id = Column(String, unique=True)
    type = Column(SQLEnum(schemas.VectorStoreType), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    files = relationship(
        "File",
        secondary=file_vector_store_association,
        back_populates="vector_stores",
        lazy="selectin",
    )
    assistants: Mapped[List["Assistant"]] = relationship(
        "Assistant",
        back_populates="vector_store",
        foreign_keys="Assistant.vector_store_id",
    )
    threads: Mapped[List["Thread"]] = relationship(
        "Thread",
        back_populates="vector_store",
        foreign_keys="Thread.vector_store_id",
    )

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def create(
        cls, session: AsyncSession, data: dict, file_ids: list[str]
    ) -> int:
        vector_store = VectorStore(**data)
        session.add(vector_store)
        await session.flush()

        if file_ids:
            file_object_ids = await File.get_object_ids_by_file_id(session, file_ids)
            file_vector_store_pairs = [
                (obj_id, vector_store.id) for obj_id in file_object_ids
            ]
            stmt = (
                _get_upsert_stmt(session)(file_vector_store_association)
                .values(file_vector_store_pairs)
                .on_conflict_do_nothing(
                    index_elements=["file_id", "vector_store_id"],
                )
            )
            await session.execute(stmt)

        await session.refresh(vector_store)
        return vector_store.id

    @classmethod
    async def get_vector_store_id_by_id(cls, session: AsyncSession, id_: int) -> str:
        stmt = select(VectorStore.vector_store_id).where(VectorStore.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "VectorStore":
        stmt = select(VectorStore).where(VectorStore.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_by_vector_store_id(
        cls, session: AsyncSession, id_: str
    ) -> "VectorStore":
        stmt = select(VectorStore).where(VectorStore.vector_store_id == id_)
        return await session.scalar(stmt)

    @classmethod
    async def delete(cls, session: AsyncSession, id_: int) -> None:
        stmt = delete(VectorStore).where(VectorStore.id == int(id_))
        await session.execute(stmt)

    @classmethod
    async def get_files_by_id(cls, session: AsyncSession, id_: int) -> List["File"]:
        stmt = select(VectorStore).where(VectorStore.id == int(id_))
        vector_store = await session.scalar(stmt)
        if not vector_store:
            return []
        return vector_store.files

    @classmethod
    async def get_file_ids_by_id(
        cls, session: AsyncSession, id_: int
    ) -> AsyncGenerator[tuple[str, int], None]:
        stmt = select(VectorStore).where(VectorStore.id == int(id_))
        vector_store = await session.scalar(stmt)
        if not vector_store:
            return
        for file in vector_store.files:
            yield file.file_id, file.id

    @classmethod
    async def get_object_id_by_vector_store_id(
        cls, session: AsyncSession, vector_store_id: str
    ) -> int:
        stmt = select(VectorStore.id).where(
            VectorStore.vector_store_id == vector_store_id
        )
        return await session.scalar(stmt)

    @classmethod
    async def add_files(
        cls, session: AsyncSession, vector_store_id: int, file_ids: list[str]
    ) -> None:
        if not file_ids:
            return
        file_object_ids = await File.get_object_ids_by_file_id(session, file_ids)
        file_vector_store_pairs = [
            (obj_id, vector_store_id) for obj_id in file_object_ids
        ]

        stmt = (
            _get_upsert_stmt(session)(file_vector_store_association)
            .values(file_vector_store_pairs)
            .on_conflict_do_nothing(
                index_elements=["file_id", "vector_store_id"],
            )
        )
        await session.execute(stmt)

    @classmethod
    async def add_files_return_id(
        cls, session: AsyncSession, vector_store_obj_id: int, file_ids: list[str]
    ) -> str:
        vector_store_id = await cls.get_vector_store_id_by_id(
            session, vector_store_obj_id
        )
        await cls.add_files(session, vector_store_obj_id, file_ids)
        return vector_store_id

    @classmethod
    async def sync_files(
        cls, session: AsyncSession, vector_store_obj_id: int, file_ids: list[str]
    ) -> tuple[str, list[str], list[str]]:
        current_file_ids = dict()
        current_file_ids = {
            file_id: file_obj_id
            async for file_id, file_obj_id in cls.get_file_ids_by_id(
                session, vector_store_obj_id
            )
        }

        new_file_ids = dict()
        new_file_ids = {
            file_id: file_obj_id
            async for file_id, file_obj_id in File.get_id_tuple_by_file_id(
                session, file_ids
            )
        }

        file_ids_to_add = {
            k: v for k, v in new_file_ids.items() if k not in current_file_ids
        }
        file_ids_to_remove = {
            k: v for k, v in current_file_ids.items() if k not in new_file_ids
        }

        vector_store_id = await cls.get_vector_store_id_by_id(
            session, vector_store_obj_id
        )

        if file_ids_to_remove:
            stmt = (
                delete(file_vector_store_association)
                .where(
                    file_vector_store_association.c.vector_store_id
                    == vector_store_obj_id
                )
                .where(
                    file_vector_store_association.c.file_id.in_(
                        file_ids_to_remove.values()
                    )
                )
            )
            await session.execute(stmt)

        if file_ids_to_add:
            await cls.add_files(
                session, vector_store_obj_id, list(file_ids_to_add.keys())
            )

        return (
            vector_store_id,
            list(file_ids_to_add.keys()),
            list(file_ids_to_remove.keys()),
        )


class Assistant(Base):
    __tablename__ = "assistants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    version = Column(Integer, default=1)
    instructions = Column(String)
    description = Column(String)
    assistant_id = Column(String)
    use_latex = Column(Boolean)
    hide_prompt = Column(Boolean, default=False)
    tools = Column(String)
    model = Column(String)
    class_id = Column(Integer, ForeignKey("classes.id"))
    class_ = relationship("Class", back_populates="assistants", foreign_keys=[class_id])
    threads = relationship("Thread", back_populates="assistant")
    files = relationship(
        "File",
        secondary=file_assistant_association,
        back_populates="assistants",
        lazy="selectin",
    )
    code_interpreter_files = relationship(
        "File",
        secondary=code_interpreter_file_assistant_association,
        back_populates="assistants_v2",
        lazy="selectin",
    )
    vector_store_id = Column(
        Integer,
        ForeignKey(
            "vector_stores.id", name="fk_assistants_vector_store_id_vector_store"
        ),
    )
    vector_store = relationship(
        "VectorStore", back_populates="assistants", uselist=False
    )
    creator_id = Column(Integer, ForeignKey("users.id"))
    creator = relationship("User", back_populates="assistants")
    published = Column(DateTime(timezone=True), index=True, nullable=True)
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Assistant":
        stmt = select(Assistant).where(Assistant.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_by_class_id(
        cls, session: AsyncSession, class_id: int
    ) -> List["Assistant"]:
        stmt = select(Assistant).where(Assistant.class_id == int(class_id))
        result = await session.execute(stmt)
        return [row.Assistant for row in result]

    @classmethod
    async def get_by_class_id_and_version(
        cls, session: AsyncSession, class_id: int, version: int
    ) -> AsyncGenerator["Assistant", None]:
        stmt = (
            select(Assistant)
            .where(Assistant.class_id == int(class_id))
            .where(Assistant.version == version)
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Assistant

    @classmethod
    async def get_all_by_id(
        cls, session: AsyncSession, ids: List[int]
    ) -> List["Assistant"]:
        if not ids:
            return []
        stmt = select(Assistant).where(Assistant.id.in_([int(id_) for id_ in ids]))
        result = await session.execute(stmt)
        return [row.Assistant for row in result]

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        data: schemas.CreateAssistant,
        *,
        class_id: int,
        user_id: int,
        assistant_id: str,
        vector_store_id: int | None = None,
        version: int = 1,
    ) -> "Assistant":
        params = data.dict()
        code_interpreter_file_ids = params.pop("code_interpreter_file_ids", [])
        params["tools"] = json.dumps(params["tools"])
        params["class_id"] = int(class_id)
        params["creator_id"] = int(user_id)
        params["assistant_id"] = assistant_id
        params["published"] = func.now() if data.published else None
        params["use_latex"] = data.use_latex
        params["vector_store_id"] = vector_store_id
        params["version"] = version

        assistant = Assistant(**params)
        session.add(assistant)
        await session.flush()

        if code_interpreter_file_ids:
            code_interpreter_file_object_ids = await File.get_object_ids_by_file_id(
                session, code_interpreter_file_ids
            )
            file_assistant_pairs = [
                (obj_id, assistant.id) for obj_id in code_interpreter_file_object_ids
            ]
            stmt = (
                _get_upsert_stmt(session)(code_interpreter_file_assistant_association)
                .values(file_assistant_pairs)
                .on_conflict_do_nothing(
                    index_elements=["file_id", "assistant_id"],
                )
            )
            await session.execute(stmt)

        await session.refresh(assistant)
        return assistant


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    institution_id = Column(Integer, ForeignKey("institutions.id"))
    institution = relationship("Institution", back_populates="classes", lazy="selectin")
    assistants: Mapped[List["Assistant"]] = relationship(
        "Assistant",
        back_populates="class_",
    )
    term = Column(String)
    api_key = Column(String, nullable=True)
    any_can_create_assistant = Column(Boolean, default=False)
    any_can_publish_assistant = Column(Boolean, default=False)
    any_can_publish_thread = Column(Boolean, default=False)
    any_can_upload_class_file = Column(Boolean, default=False)
    users: Mapped[List["UserClassRole"]] = relationship(
        "UserClassRole",
        back_populates="class_",
    )
    files: Mapped[List["File"]] = relationship("File", back_populates="class_")
    threads = relationship("Thread", back_populates="class_")
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def get_members(
        cls,
        session: AsyncSession,
        id_: int,
        limit: int = 10,
        offset: int = 0,
        search: str = "",
    ) -> AsyncGenerator["UserClassRole", None]:
        condition = UserClassRole.class_id == int(id_)
        if search:
            condition = and_(condition, User.email.ilike(f"%{search}%"))
        stmt = (
            select(UserClassRole)
            .join(User)
            .options(joinedload(UserClassRole.user))
            .where(condition)
            .order_by(User.email)
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.UserClassRole

    @classmethod
    async def get_member_count(
        cls,
        session: AsyncSession,
        id_: int,
        search: str = "",
    ) -> int:
        condition = UserClassRole.class_id == int(id_)
        if search:
            condition = and_(condition, User.email.ilike(f"%{search}%"))
        stmt = (
            select(func.count()).select_from(UserClassRole).join(User).where(condition)
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_api_key(cls, session: AsyncSession, id_: int) -> str | None:
        stmt = select(Class.api_key).where(Class.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def update_api_key(
        cls, session: AsyncSession, id_: int, api_key: str
    ) -> None:
        stmt = update(Class).where(Class.id == int(id_)).values(api_key=api_key)
        await session.execute(stmt)

    @classmethod
    async def create(
        cls, session: AsyncSession, inst_id: int, data: schemas.CreateClass
    ) -> "Class":
        class_ = Class(institution_id=inst_id, **data.dict())
        session.add(class_)
        await session.flush()
        await session.refresh(class_)
        await class_.awaitable_attrs.institution
        return class_

    @classmethod
    async def update(
        cls, session: AsyncSession, id_: int, data: schemas.UpdateClass
    ) -> "Class":
        stmt = (
            update(Class)
            .where(Class.id == int(id_))
            .values(**data.dict(exclude_none=True))
        )
        await session.execute(stmt)
        return await cls.get_by_id(session, int(id_))

    @classmethod
    async def get_by_institution(
        cls, session: AsyncSession, institution_id: int
    ) -> List["Class"]:
        stmt = (
            select(Class)
            .options(joinedload(Class.institution))
            .where(Class.institution_id == int(institution_id))
        )
        result = await session.execute(stmt)
        return [row.Class for row in result]

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Class":
        stmt = (
            select(Class)
            .options(joinedload(Class.institution))
            .where(Class.id == int(id_))
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_all_by_id(
        cls, session: AsyncSession, ids: list[int]
    ) -> list["Class"]:
        if not ids:
            return []
        stmt = (
            select(Class)
            .options(joinedload(Class.institution))
            .where(Class.id.in_(ids))
        )
        result = await session.execute(stmt)
        return [row.Class for row in result]

    @classmethod
    async def get_all_with_api_key(
        cls, session: AsyncSession
    ) -> AsyncGenerator["Class", None]:
        stmt = select(Class).where(Class.api_key.is_not(None))
        result = await session.execute(stmt)
        for row in result:
            yield row.Class


class CodeInterpreterCall(Base):
    __tablename__ = "code_interpreter_calls"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, default=2)
    run_id = Column(String)
    step_id = Column(String, unique=True)
    thread_id = Column(Integer, ForeignKey("threads.id"))
    thread = relationship(
        "Thread", back_populates="code_interpreter_calls", uselist=False
    )
    created_at = Column(Integer, index=True)
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(
        cls, session: AsyncSession, data: dict, thread_obj_id: int | None = None
    ) -> None:
        data["thread_id"] = (
            thread_obj_id
            if thread_obj_id
            else await Thread.get_id_by_thread_id(session, data["thread_id"])
        )
        stmt = (
            _get_upsert_stmt(session)(CodeInterpreterCall)
            .values(
                **data,
            )
            .on_conflict_do_nothing(
                index_elements=["step_id"],
            )
        )
        await session.execute(stmt)

    @classmethod
    async def get_calls(
        cls,
        session: AsyncSession,
        thread_id: int,
        after: int,
        before: int | None = None,
        desc: bool = True,
    ) -> AsyncGenerator["CodeInterpreterCall", None]:
        conditions = [CodeInterpreterCall.thread_id == thread_id, CodeInterpreterCall.created_at >= after]
        if before:
            conditions.append(CodeInterpreterCall.created_at <= before)
        stmt = select(CodeInterpreterCall).where(and_(*conditions)).order_by(CodeInterpreterCall.created_at.desc()
                if desc
                else CodeInterpreterCall.created_at.asc()
            )
        result = await session.execute(stmt)
        for row in result:
            yield row.CodeInterpreterCall


class Thread(Base):
    __tablename__ = "threads"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    version = Column(Integer, default=1)
    thread_id = Column(String, unique=True)
    class_id = Column(Integer, ForeignKey("classes.id"))
    class_ = relationship("Class", back_populates="threads", lazy="selectin")
    assistant_id = Column(Integer, ForeignKey("assistants.id"))
    assistant = relationship("Assistant", back_populates="threads", uselist=False)
    private = Column(Boolean)
    users = relationship(
        "User",
        secondary=user_thread_association,
        back_populates="threads",
        lazy="subquery",
    )
    code_interpreter_files = relationship(
        "File",
        secondary=code_interpreter_file_thread_association,
        back_populates="threads",
        lazy="selectin",
    )
    code_interpreter_calls = relationship(
        "CodeInterpreterCall",
        back_populates="thread",
    )
    tools_available = Column(String)
    vector_store_id = Column(
        Integer,
        ForeignKey("vector_stores.id", name="fk_threads_vector_store_id_vector_store"),
    )
    vector_store = relationship("VectorStore", back_populates="threads", uselist=False)
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        index=True,
        server_default=func.now(),
        onupdate=func.now(),
    )

    async def delete(self, session: AsyncSession) -> None:
        for user in self.users:
            self.users.remove(user)
        stmt = delete(Thread).where(Thread.id == self.id)
        await session.execute(stmt)

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "Thread":
        code_interpreter_file_ids = data.pop("code_interpreter_file_ids", [])
        thread = Thread(**data)
        session.add(thread)
        await session.flush()

        if code_interpreter_file_ids:
            code_interpreter_file_object_ids = await File.get_object_ids_by_file_id(
                session, code_interpreter_file_ids
            )
            file_thread_pairs = [
                (obj_id, thread.id) for obj_id in code_interpreter_file_object_ids
            ]
            stmt = (
                _get_upsert_stmt(session)(code_interpreter_file_thread_association)
                .values(file_thread_pairs)
                .on_conflict_do_nothing(
                    index_elements=["file_id", "thread_id"],
                )
            )
            await session.execute(stmt)

        await session.refresh(thread)
        return thread

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Thread":
        stmt = select(Thread).where(Thread.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_id_by_thread_id(cls, session: AsyncSession, thread_id: str) -> int:
        stmt = select(Thread.id).where(Thread.thread_id == thread_id)
        return await session.scalar(stmt)

    @classmethod
    async def get_n_by_id(
        cls,
        session: AsyncSession,
        ids: list[int],
        n: int = 10,
        before: datetime | None = None,
        **kwargs,
    ) -> List["Thread"]:
        """Similar to `get_all_by_id` but tries to guarantee `n` results.

        This is useful if we suspect that some of the `ids` in the input do not exist;
        we will keep querying until we have `n` results or we run out of threads to query.
        """
        if n < 1:
            return []
        # We might need to issue multiple queries in case the information in the authz
        # server is out of date (e.g., threads have been deleted but the authz server
        # still thinks they exist).
        threads: List["Thread"] = []
        next_latest_time: datetime | None = before
        while len(threads) < n:
            added_in_page = 0
            async for new_thread in cls.get_all_by_id(
                session, ids, limit=n, before=next_latest_time, **kwargs
            ):
                if not next_latest_time or new_thread.updated < next_latest_time:
                    next_latest_time = new_thread.updated

                threads.append(new_thread)
                added_in_page += 1

                if len(threads) >= n:
                    break
            if not added_in_page:
                break
        return threads

    @classmethod
    async def get_all_by_id(
        cls,
        session: AsyncSession,
        ids: list[int],
        limit: int = 10,
        before: datetime | None = None,
        class_id: int | None = None,
        private: bool | None = None,
    ) -> AsyncGenerator["Thread", None]:
        """Get a number of threads by their IDs.

        Might not return exactly the number of threads requested.
        See `get_n_by_id` for a version that tries to guarantee `n` results
        if possible.
        """
        if not ids:
            return

        condition = Thread.id.in_([int(id_) for id_ in ids])
        if before:
            condition = and_(condition, Thread.updated < before)
        if class_id:
            condition = and_(condition, Thread.class_id == int(class_id))
        if private is not None:
            condition = and_(condition, Thread.private == private)

        stmt = (
            select(Thread).order_by(Thread.updated.desc()).where(condition).limit(limit)
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Thread

    @classmethod
    async def get_by_class_id(
        cls,
        session: AsyncSession,
        class_id: int,
        limit: int = 10,
        before: datetime | None = None,
    ) -> AsyncGenerator["Thread", None]:
        condition = Thread.class_id == int(class_id)
        if before:
            condition = and_(condition, Thread.updated < before)
        stmt = select(Thread).order_by(Thread.updated.desc()).where(condition)
        if limit:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        for row in result:
            yield row.Thread

    @classmethod
    async def add_code_interpeter_files(
        cls, session: AsyncSession, thread_id: int, file_ids: list[str]
    ) -> None:
        if not file_ids:
            return
        file_object_ids = await File.get_object_ids_by_file_id(session, file_ids)
        file_thread_pairs = [(obj_id, thread_id) for obj_id in file_object_ids]
        stmt = (
            _get_upsert_stmt(session)(code_interpreter_file_thread_association)
            .values(file_thread_pairs)
            .on_conflict_do_nothing(
                index_elements=["file_id", "thread_id"],
            )
        )
        await session.execute(stmt)

    @classmethod
    async def get_file_ids_by_id(
        cls, session: AsyncSession, id_: int
    ) -> AsyncGenerator[str, None]:
        stmt = select(Thread).where(Thread.id == int(id_))
        thread = await session.scalar(stmt)
        if not thread:
            return
        for file in thread.code_interpreter_files:
            yield file.file_id

    @classmethod
    async def get_by_class_id_and_version(
        cls, session: AsyncSession, class_id: int, version: int
    ) -> AsyncGenerator["Thread", None]:
        stmt = (
            select(Thread)
            .options(joinedload(Thread.assistant))
            .where(Thread.class_id == int(class_id))
            .where(Thread.version == version)
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Thread
