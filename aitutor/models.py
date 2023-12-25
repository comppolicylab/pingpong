import json
from enum import Enum
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    and_,
    delete,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import false

import aitutor.schemas as schemas


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
    role: Mapped[Optional[str]]
    title: Mapped[Optional[str]]
    user = relationship("User", back_populates="classes")
    class_ = relationship("Class", back_populates="users")

    @classmethod
    async def get(
        cls, session: AsyncSession, user_id: int, class_id: int
    ) -> Optional["UserClassRole"]:
        stmt = select(UserClassRole).where(
            and_(UserClassRole.user_id == user_id, UserClassRole.class_id == class_id)
        )
        return await session.scalar(stmt)

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        user_id: int,
        class_id: int,
        ucr: schemas.CreateUserClassRole,
    ) -> "UserClassRole":
        user_class_role = UserClassRole(
            user_id=user_id, class_id=class_id, title=ucr.title, role=ucr.role
        )
        session.add(user_class_role)
        return user_class_role

    @classmethod
    async def delete(cls, session: AsyncSession, user_id: int, class_id: int) -> None:
        stmt = delete(UserClassRole).where(
            and_(UserClassRole.user_id == user_id, UserClassRole.class_id == class_id)
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
    role: Mapped[Optional[str]]
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


class UserState(Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    BANNED = "banned"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String, nullable=True)
    email = Column(String, unique=True)
    state = Column(String)
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
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    async def verify(self, session: AsyncSession) -> None:
        self.state = UserState.VERIFIED
        session.add(self)

    @classmethod
    async def get_by_email(cls, session: AsyncSession, email: str) -> "User":
        stmt = select(User).where(User.email == email)
        return await session.scalar(stmt)

    @classmethod
    async def get_or_create_by_email(
        cls,
        session: AsyncSession,
        email: str,
        initial_state: UserState = UserState.UNVERIFIED,
    ) -> "User":
        existing = await cls.get_by_email(session, email)
        if existing:
            return existing
        user = User(email=email, state=initial_state)
        session.add(user)
        session.flush()
        session.refresh(user)
        return user

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id: int) -> "User":
        stmt = select(User).where(User.id == id)
        return await session.scalar(stmt)

    @classmethod
    async def get_all_by_id(cls, session: AsyncSession, ids: List[int]) -> List["User"]:
        if not ids:
            return []
        stmt = select(User).where(User.id.in_(ids))
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
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def can_read(
        cls, session: AsyncSession, institution_id: int, user: User
    ) -> bool:
        stmt = select(UserInstitutionRole).where(
            and_(
                UserInstitutionRole.user_id == user.id,
                UserInstitutionRole.institution_id == institution_id,
            )
        )
        result = await session.scalar(stmt)
        return result is not None

    @classmethod
    async def can_write(
        cls, session: AsyncSession, institution_id: int, user: User
    ) -> bool:
        stmt = select(UserInstitutionRole).where(
            and_(
                UserInstitutionRole.user_id == user.id,
                UserInstitutionRole.institution_id == institution_id,
                UserInstitutionRole.role == "admin",
            )
        )
        result = await session.scalar(stmt)
        return result is not None

    @classmethod
    async def can_manage(
        cls, session: AsyncSession, institution_id: int, user: User
    ) -> bool:
        return False

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "Institution":
        institution = Institution(**data)
        session.add(institution)
        await session.flush()
        await session.refresh(institution)
        return institution

    @classmethod
    async def all(cls, session: AsyncSession) -> List["Institution"]:
        stmt = select(Institution)
        result = await session.execute(stmt)
        return [row.Institution for row in result]

    @classmethod
    async def visible(cls, session: AsyncSession, user: User) -> List["Institution"]:
        stmt = (
            select(Institution)
            .join(UserInstitutionRole)
            .where(UserInstitutionRole.user_id == user.id)
        )
        return await session.scalars(stmt)

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id: int) -> "Institution":
        stmt = select(Institution).where(Institution.id == id)
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
    class_ = relationship("Class", back_populates="files")
    assistants = relationship(
        "Assistant", secondary=file_assistant_association, back_populates="files"
    )

    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "File":
        file = File(**data)
        session.add(file)
        await session.flush()
        await session.refresh(file)
        return file

    @classmethod
    async def for_class(cls, session: AsyncSession, class_id: int) -> list["File"]:
        stmt = select(File).where(File.class_id == class_id)
        result = await session.execute(stmt)
        return [row.File for row in result]

    @classmethod
    async def get_all_by_file_id(
        cls, session: AsyncSession, ids: List[str]
    ) -> List["File"]:
        stmt = select(File).where(File.file_id.in_(ids))
        result = await session.execute(stmt)
        return [row.File for row in result]


class Assistant(Base):
    __tablename__ = "assistants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    instructions = Column(String)
    assistant_id = Column(String)
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
    published = Column(Integer, index=True, nullable=True)
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def can_manage(
        cls, session: AsyncSession, assistant_id: int, user: User
    ) -> bool:
        asst = await cls.get_by_id(session, assistant_id)
        if not asst:
            return False

        return asst.creator_id == user.id

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Assistant":
        stmt = select(Assistant).where(Assistant.id == id_)
        return await session.scalar(stmt)

    @classmethod
    async def get_all_by_id(
        cls, session: AsyncSession, ids: List[int]
    ) -> List["Assistant"]:
        if not ids:
            return []
        stmt = select(Assistant).where(Assistant.id.in_(ids))
        result = await session.execute(stmt)
        return [row.Assistant for row in result]

    @classmethod
    async def for_class(cls, session: AsyncSession, class_id: int) -> list["Assistant"]:
        stmt = select(Assistant).where(
            and_(Assistant.class_id == class_id, Assistant.published.is_not(None))
        )
        result = await session.execute(stmt)
        return [row.Assistant for row in result]

    @classmethod
    async def for_user(cls, session: AsyncSession, user_id: int) -> list["Assistant"]:
        stmt = select(Assistant).where(Assistant.creator_id == user_id)
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
        assistant_id: str
    ) -> "Assistant":
        params = data.dict()
        file_ids = params.pop("file_ids", [])
        files = []
        if file_ids:
            files = await File.get_all_by_file_id(session, file_ids)
        params["files"] = files
        params["tools"] = json.dumps(params["tools"])
        params["class_id"] = class_id
        params["creator_id"] = user_id
        params["assistant_id"] = assistant_id
        params["published"] = None

        assistant = Assistant(**params)
        session.add(assistant)
        await session.flush()
        await session.refresh(assistant)
        return assistant

    @classmethod
    async def publish(cls, session: AsyncSession, assistant_id: int) -> "Assistant":
        stmt = (
            update(Assistant)
            .where(Assistant.id == assistant_id)
            .values(published=func.now())
            .returning(Assistant)
        )
        return await session.scalar(stmt)


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    institution_id = Column(Integer, ForeignKey("institutions.id"))
    institution = relationship("Institution", back_populates="classes")
    assistants: Mapped[List["Assistant"]] = relationship(
        "Assistant", back_populates="class_", lazy="selectin"
    )
    term = Column(String)
    api_key = Column(String, nullable=True)
    users: Mapped[List["UserClassRole"]] = relationship(
        "UserClassRole", back_populates="class_", lazy="selectin"
    )
    files: Mapped[List["File"]] = relationship("File", back_populates="class_")
    threads = relationship("Thread", back_populates="class_", lazy="selectin")
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def get_api_key(cls, session: AsyncSession, id: int) -> str | None:
        stmt = select(Class.api_key).where(Class.id == id)
        return await session.scalar(stmt)

    @classmethod
    async def update_api_key(cls, session: AsyncSession, id: int, api_key: str) -> None:
        stmt = update(Class).where(Class.id == id).values(api_key=api_key)
        await session.execute(stmt)

    @classmethod
    async def can_manage(cls, session: AsyncSession, class_id: int, user: User) -> bool:
        class_ = await session.scalar(select(Class).where(Class.id == class_id))

        if not class_:
            return False

        # Match the class._users to the given user by id:
        for user_class in class_.users:
            if user_class.user_id == user.id:
                return user_class.role == "admin"

        return False

    @classmethod
    async def can_write(cls, session: AsyncSession, class_id: int, user: User) -> bool:
        class_ = await session.scalar(select(Class).where(Class.id == class_id))

        if not class_:
            return False

        # Match the class._users to the given user by id:
        for user_class in class_.users:
            if user_class.user_id == user.id:
                return user_class.role in ("admin", "write")

        return False

    @classmethod
    async def can_read(cls, session: AsyncSession, class_id: int, user: User) -> bool:
        class_ = await session.scalar(select(Class).where(Class.id == class_id))

        if not class_:
            return False

        # Match the class._users to the given user by id:
        for user_class in class_.users:
            if user_class.user_id == user.id:
                return True

        return False

    @classmethod
    async def create(cls, session: AsyncSession, data: schemas.CreateClass) -> "Class":
        class_ = Class(**data.dict())
        session.add(class_)
        await session.flush()
        await session.refresh(class_)
        return class_

    @classmethod
    async def update(
        cls, session: AsyncSession, id: int, data: schemas.UpdateClass
    ) -> "Class":
        stmt = (
            update(Class).where(Class.id == id).values(**data.dict(exclude_none=True))
        )
        await session.execute(stmt)
        return await cls.get_by_id(session, id)

    @classmethod
    async def get_by_institution(
        cls, session: AsyncSession, institution_id: int
    ) -> List["Class"]:
        stmt = select(Class).where(Class.institution_id == institution_id)
        result = await session.execute(stmt)
        return [row.Class for row in result]

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id: int) -> "Class":
        stmt = select(Class).where(Class.id == id)
        return await session.scalar(stmt)


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
        lazy="selectin",
    )
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

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
    async def get_by_id(cls, session: AsyncSession, id: int) -> "Thread":
        stmt = select(Thread).where(Thread.id == id)
        return await session.scalar(stmt)

    @classmethod
    async def can_read(self, session: AsyncSession, thread_id: int, user: User) -> bool:
        thread = await session.scalar(select(Thread).where(Thread.id == thread_id))

        if not thread:
            return False

        if thread.private:
            return user in thread.users
        else:
            return user in thread.class_.users

    @classmethod
    async def all(cls, session: AsyncSession, class_id: int) -> List["Thread"]:
        stmt = select(Thread).where(Thread.class_id == class_id)
        result = await session.execute(stmt)
        return [row.Thread for row in result]

    @classmethod
    async def visible(
        cls, session: AsyncSession, class_id: int, user: User
    ) -> List["Thread"]:
        # Get all non-private threads for the class_id,
        # plus any threads that are private in the class but which the
        # user is a participant of.

        # Private threads
        # Get IDs of private threads from the `user_thread_association` table
        # where the user is a participant.
        p_stmt = select(user_thread_association).where(
            user_thread_association.c.user_id == user.id
        )
        result = await session.execute(p_stmt)
        private_thread_ids = [row.thread_id for row in result]

        # Now select all threads for the class that are either public or
        # which are included in the visible private thread IDs list.
        stmt = select(Thread).where(
            and_(
                Thread.class_id == class_id,
                or_(Thread.private == false(), Thread.id.in_(private_thread_ids)),
            )
        )
        result = await session.execute(stmt)
        return [row.Thread for row in result]
