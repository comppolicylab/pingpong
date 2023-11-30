from sqlalchemy import (
        Table,
        Column,
        Boolean,
        ForeignKey,
        Integer,
        String,
        Index,
        select,
        )
from sqlalchemy.sql import func
from sqlalchemy.ext.asyncio import (
        async_sessionmaker,
        AsyncAttrs,
        AsyncSession,
        create_async_engine,
        )
from sqlalchemy.orm import (
        DeclarativeBase,
        relationship,
        )


class Base(AsyncAttrs, DeclarativeBase):
    pass


user_class_association = Table(
        'users_classes',
        Base.metadata,
        Column('user_id', Integer, ForeignKey('users.id')),
        Column('class_id', Integer, ForeignKey('classes.id')),
        Index('user_class_idx', 'user_id', 'class_id', unique=True),
        )


user_thread_association = Table(
        'users_threads',
        Base.metadata,
        Column('user_id', Integer, ForeignKey('users.id')),
        Column('thread_id', Integer, ForeignKey('threads.id')),
        Index('user_thread_idx', 'user_id', 'thread_id', unique=True),
        )


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    classes = relationship('Class', secondary=user_class_association, back_populates='users')
    roles = relationship('UserClassRole', back_populates='users', lazy='selectin')
    threads = relationship('Thread', secondary=user_thread_association, back_populates='users')
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def get_by_email(cls, session: AsyncSession, email: str) -> 'User':
        stmt = select(User).where(User.email == email)
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id: int) -> 'User':
        stmt = select(User).where(User.id == id)
        return await session.scalar(stmt)


class Institution(Base):
    __tablename__ = 'institutions'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    classes = relationship('Class', back_populates='institution')
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())


class Class(Base):
    __tablename__ = 'classes'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    institution_id = Column(Integer, ForeignKey('institutions.id'))
    institution = relationship('Institution', back_populates='classes')
    term = Column(String)
    users = relationship('User', secondary=user_class_association, back_populates='classes')
    threads = relationship('Thread', back_populates='class_')
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())


class UserClassRole(Base):
    __tablename__ = 'users_class_roles'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    class_id = Column(Integer, ForeignKey('classes.id'))
    role = Column(String)

    users = relationship('User', back_populates='roles')


class Thread(Base):
    __tablename__ = 'threads'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    thread_id = Column(String, unique=True)
    class_id = Column(Integer, ForeignKey('classes.id'))
    class_ = relationship('Class', back_populates='threads')
    private = Column(Boolean)
    users = relationship('User', secondary=user_thread_association, back_populates='threads')
    created = Column(Integer, server_default=func.now())
    updated = Column(Integer, index=True, onupdate=func.now())

    @classmethod
    async def can_read(self, session: AsyncSession, thread_id: int, user: User) -> bool:
        thread = await session.scalar(
                select(Thread).where(Thread.id == thread_id))

        if not thread:
            return False

        print("thread.private", thread, user)

        if thread.private:
            return user in thread.users
        else:
            return user in thread.class_.users


async def init_db(drop_first: bool = False):
    engine = create_async_engine('sqlite+aiosqlite:///db.sqlite3', echo=True)

    async with engine.begin() as conn:
        if drop_first:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()


def get_async_session():
    engine = create_async_engine('sqlite+aiosqlite:///db.sqlite3', echo=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async_session = get_async_session()
