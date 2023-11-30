from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
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


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    institution_id = Column(Integer, ForeignKey("institutions.id"))
    institution = relationship("Institution", back_populates="classes")
    term = Column(String)
    users: Mapped[List["UserClassRole"]] = relationship(
        "UserClassRole", back_populates="class_"
    )
    threads = relationship("Thread", back_populates="class_")
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


class Thread(Base):
    __tablename__ = "threads"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    thread_id = Column(String, unique=True)
    class_id = Column(Integer, ForeignKey("classes.id"))
    class_ = relationship("Class", back_populates="threads")
    private = Column(Boolean)
    users = relationship(
        "User", secondary=user_thread_association, back_populates="threads"
    )
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def can_read(self, session: AsyncSession, thread_id: int, user: User) -> bool:
        thread = await session.scalar(select(Thread).where(Thread.id == thread_id))

        if not thread:
            return False

        print("thread.private", thread, user)

        if thread.private:
            return user in thread.users
        else:
            return user in thread.class_.users


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
