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
    name = Column(String, nullable=True)
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
        "Assistant", secondary=file_assistant_association, back_populates="files"
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


class Assistant(Base):
    __tablename__ = "assistants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
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
    ) -> "Assistant":
        params = data.dict()
        file_ids = params.pop("file_ids", [])
        files = []
        if file_ids:
            files = await File.get_all_by_file_id(session, file_ids)
        params["files"] = files
        params["tools"] = json.dumps(params["tools"])
        params["class_id"] = int(class_id)
        params["creator_id"] = int(user_id)
        params["assistant_id"] = assistant_id

        params["published"] = func.now() if data.published else None
        params["use_latex"] = data.use_latex

        assistant = Assistant(**params)
        session.add(assistant)
        await session.flush()
        await session.refresh(assistant)
        return assistant

    async def delete(self, session: AsyncSession):
        await session.delete(self)
        await session.flush()


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


class Thread(Base):
    __tablename__ = "threads"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    thread_id = Column(String, unique=True)
    class_id = Column(Integer, ForeignKey("classes.id"))
    class_ = relationship("Class", back_populates="threads", lazy="selectin")
    assistant_id = Column(Integer, ForeignKey("assistants.id"))
    assistant = relationship("Assistant", back_populates="threads")
    private = Column(Boolean)
    users = relationship(
        "User",
        secondary=user_thread_association,
        back_populates="threads",
        lazy="subquery",
    )
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        index=True,
        server_default=func.now(),
        onupdate=func.now(),
    )

    async def delete(self, session: AsyncSession) -> None:
        stmt = delete(Thread).where(Thread.id == self.id)
        await session.execute(stmt)

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "Thread":
        thread = Thread(**data)
        session.add(thread)
        await session.flush()
        await session.refresh(thread)
        return thread

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Thread":
        stmt = select(Thread).where(Thread.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_all_by_id(
        cls,
        session: AsyncSession,
        ids: list[int],
        limit: int = 10,
        before: datetime | None = None,
    ) -> AsyncGenerator["Thread", None]:
        if not ids:
            return

        condition = Thread.id.in_([int(id_) for id_ in ids])
        if before:
            condition = and_(condition, Thread.updated < before)

        stmt = select(Thread).order_by(Thread.updated.desc()).where(condition)
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
        stmt = (
            select(Thread).order_by(Thread.updated.desc()).where(condition).limit(limit)
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Thread
