from sqlalchemy import (
        Column,
        Boolean,
        ForeignKey,
        Integer,
        String,
        Index,
        )
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


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    classes = relationship('UserClass', back_populates='user_id')
    roles = relationship('UserClassRole', back_populates='user_id')
    threads = relationship('UserThread', back_populates='user_id')
    created = Column(Integer)
    updated = Column(Integer, index=True)


class Institution(Base):
    __tablename__ = 'institutions'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    classes = relationship('Class', back_populates='institution')
    created = Column(Integer)
    updated = Column(Integer, index=True)


class Class(Base):
    __tablename__ = 'classes'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    institution_id = Column(Integer, ForeignKey('institutions.id'))
    term = Column(String)
    users = relationship('UserClass', back_populates='class_id')
    threads = relationship('Thread', back_populates='class_id')
    created = Column(Integer)
    updated = Column(Integer, index=True)


class UserClass(Base):
    __tablename__ = 'users_classes'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    class_id = Column(Integer, ForeignKey('classes.id'))


class UserClassRole(Base):
    __tablename__ = 'users_class_roles'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    class_id = Column(Integer, ForeignKey('classes.id'))
    role = Column(String)


# Many:many mapping from users to threads
class UserThread(Base):
    __tablename__ = 'users_threads'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    thread_id = Column(Integer, ForeignKey('threads.id'))


class Thread(Base):
    __tablename__ = 'threads'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    thread_id = Column(String)
    class_id = Column(Integer, ForeignKey('classes.id'))
    private = Column(Boolean)
    users = relationship('UserThread', back_populates='thread_id')
    created = Column(Integer)
    updated = Column(Integer, index=True)


async def init_db(drop_first: bool = False):
    engine = create_async_engine('sqlite+aiosqlite:///db.sqlite3', echo=True)

    async with engine.begin() as conn:
        if drop_first:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
