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
    or_,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import false


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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    state = Column(String)
    classes: Mapped[List["UserClassRole"]] = relationship(
        back_populates="user", lazy="selectin"
    )
    institutions: Mapped[List["UserInstitutionRole"]] = relationship(
        back_populates="user", lazy="selectin"
    )
    super_admin = Column(Boolean, default=False)
    threads = relationship(
        "Thread", secondary=user_thread_association, back_populates="users"
    )
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def get_by_email(cls, session: AsyncSession, email: str) -> "User":
        stmt = select(User).where(User.email == email)
        return await session.scalar(stmt)

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
    class_ = relationship("Class", back_populates="assistants")
    files = relationship(
        "File", secondary=file_assistant_association, back_populates="assistants"
    )
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def for_class(cls, session: AsyncSession, class_id: int) -> list["Assistant"]:
        stmt = select(Assistant).where(Assistant.class_id == class_id)
        result = await session.execute(stmt)
        return [row.Assistant for row in result]

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "Assistant":
        assistant = Assistant(**data)
        session.add(assistant)
        await session.flush()
        await session.refresh(assistant)
        return assistant


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
    users: Mapped[List["UserClassRole"]] = relationship(
        "UserClassRole", back_populates="class_", lazy="selectin"
    )
    files: Mapped[List["File"]] = relationship("File", back_populates="class_")
    threads = relationship("Thread", back_populates="class_", lazy="selectin")
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

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
    async def create(cls, session: AsyncSession, data: dict) -> "Class":
        class_ = Class(**data)
        session.add(class_)
        await session.flush()
        await session.refresh(class_)
        return class_

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
    private = Column(Boolean)
    users = relationship(
        "User",
        secondary=user_thread_association,
        back_populates="threads",
        lazy="selectin",
    )
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

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


async def init_db(drop_first: bool = False):
    engine = create_async_engine("sqlite+aiosqlite:///db.sqlite3", echo=True)

    async with engine.begin() as conn:
        if drop_first:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()


def get_async_session():
    engine = create_async_engine("sqlite+aiosqlite:///db.sqlite3", echo=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async_session = get_async_session()
