import asyncio
import json
from datetime import datetime
from typing import AsyncGenerator, List, Optional, Union

from sqlalchemy import Boolean, Column, Computed, DateTime, Float, UniqueConstraint
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
    contains_eager,
    selectinload,
    mapped_column,
    relationship,
)
from sqlalchemy.sql import func
import pingpong.schemas as schemas
import logging


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
    __table_args__ = (UniqueConstraint("user_id", "class_id", name="_user_class_uc"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="cascade"), nullable=False, primary_key=True
    )
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="cascade"), nullable=False, primary_key=True
    )
    role = Column(SQLEnum(schemas.Role), nullable=True)
    title: Mapped[Optional[str]]
    lms_tenant: Mapped[Optional[str]]
    lms_type = Column(SQLEnum(schemas.LMSType), nullable=True)
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
        lms_tenant: str | None = None,
        lms_type: schemas.LMSType | None = None,
        sso_tenant: str | None = None,
        sso_id: str | None = None,
    ) -> "UserClassRole":
        stmt = (
            _get_upsert_stmt(session)(UserClassRole)
            .values(
                user_id=int(user_id),
                class_id=int(class_id),
                lms_tenant=lms_tenant,
                lms_type=lms_type,
            )
            .on_conflict_do_update(
                index_elements=[UserClassRole.user_id, UserClassRole.class_id],
                set_=dict(
                    lms_tenant=lms_tenant,
                    lms_type=lms_type,
                ),
            )
            .returning(UserClassRole)
        )
        result = await session.scalar(stmt)
        if sso_tenant and sso_id:
            stmt_ = (
                _get_upsert_stmt(session)(ExternalLogin)
                .values(user_id=user_id, provider=sso_tenant, identifier=sso_id)
                .on_conflict_do_update(
                    index_elements=["user_id", "provider"],
                    set_=dict(
                        provider=sso_tenant,
                        identifier=sso_id,
                    ),
                )
            )
            await session.execute(stmt_)
        return result

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

    @classmethod
    async def delete_from_sync_list(
        cls,
        session: AsyncSession,
        class_id: int,
        newly_synced: list[int],
        lms_tenant: str,
        lms_type: schemas.LMSType,
    ) -> list[int]:
        """
        Removes `UserClassRole`s from LMS course members who were previously synced with a specific LMS tenant but were not returned in the current sync.

        Args:
            session (AsyncSession): The DB Session to use for executing DB statements.
            class_id (int): The ID of the class being synced.
            newly_synced (list[int]): The list of all user ids returned by the current sync.
            lms (str): The LMS tenant the sync was performed on.

        Returns:
            list[int]: List of user ids that were removed as they were not included in the current LMS tenant sync. Can be used to remove the relevant permissions for users.
        """
        stmt = select(UserClassRole).where(
            and_(
                UserClassRole.class_id == int(class_id),
                UserClassRole.lms_tenant == lms_tenant,
                UserClassRole.lms_type == lms_type,
            )
        )
        result = await session.execute(stmt)
        users = [row.UserClassRole.user_id for row in result]
        users_to_delete = list(set(users) - set(newly_synced))
        stmt_ = delete(UserClassRole).where(
            and_(
                UserClassRole.class_id == int(class_id),
                UserClassRole.user_id.in_(users_to_delete),
            )
        )
        await session.execute(stmt_)
        return users_to_delete


class UserInstitutionRole(Base):
    __tablename__ = "users_institutions"
    __table_args__ = (
        UniqueConstraint("user_id", "institution_id", name="_user_inst_uc"),
    )

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


class ExternalLogin(Base):
    __tablename__ = "external_logins"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="_user_provider_uc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="external_logins")
    provider = Column(String, nullable=False)
    identifier = Column(String, nullable=False)

    @classmethod
    async def create_or_update(
        cls, session: AsyncSession, user_id: int, provider: str, identifier: str
    ) -> None:
        stmt = (
            _get_upsert_stmt(session)(ExternalLogin)
            .values(user_id=user_id, provider=provider, identifier=identifier)
            .on_conflict_do_update(
                index_elements=["user_id", "provider"],
                set_=dict(identifier=identifier),
            )
        )
        await session.execute(stmt)

    @classmethod
    async def accounts_to_merge(
        cls, session: AsyncSession, user_id: int, provider: str, identifier: str
    ) -> list[int]:
        stmt_ = select(ExternalLogin.user_id).where(
            and_(
                ExternalLogin.provider == provider,
                ExternalLogin.identifier == identifier,
                ExternalLogin.user_id != user_id,
            )
        )
        result = await session.execute(stmt_)
        return list(set(row[0] for row in result))


user_merge_association = Table(
    "users_merged_users",
    Base.metadata,
    Column(
        "user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ),
    Column("merged_user_id", Integer, nullable=False),
    Index("user_user_id_idx", "user_id", "merged_user_id", unique=True),
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
    external_logins: Mapped[List["ExternalLogin"]] = relationship(
        "ExternalLogin", back_populates="user", lazy="selectin"
    )
    # Maps to classes in which the user has connected their LMS account
    lms_syncs: Mapped[List["Class"]] = relationship(
        "Class", back_populates="lms_user", lazy="selectin"
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
    async def get_by_email_sso(
        cls,
        session: AsyncSession,
        email: str,
        provider: str | None,
        identifier: str | None,
    ) -> "User":
        # First attempt: query by email
        stmt_by_email = select(User).where(func.lower(User.email) == func.lower(email))
        user = await session.scalar(stmt_by_email)

        if user or not provider or not identifier:
            return user

        # If user is not found by email, attempt to query by external login
        stmt_by_sso = (
            select(User)
            .join(ExternalLogin)
            .where(
                and_(
                    ExternalLogin.provider == provider,
                    ExternalLogin.identifier == identifier,
                )
            )
        )

        user_ = await session.scalar(stmt_by_sso)
        return user_

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
    async def get_or_create_by_email_sso(
        cls,
        session: AsyncSession,
        email: str,
        provider: str | None,
        identifier: str | None,
        initial_state: schemas.UserState = schemas.UserState.UNVERIFIED,
        display_name: str | None = None,
    ) -> "User":
        if not provider:
            logging.warning(
                f"get_by_email_sso: Provider is missing, identifier is {identifier}"
            )
        if not identifier:
            logging.warning(
                f"get_by_email_sso: Identifier is missing, provider is {provider}"
            )
        existing = await cls.get_by_email_sso(
            session, email, provider=provider, identifier=identifier
        )
        # User already exists
        if existing:
            if provider and identifier:
                # We might not have the external login information stored
                await ExternalLogin.create_or_update(
                    session, existing.id, provider=provider, identifier=identifier
                )
            # Now that we updated the external login, we can return the user
            await session.refresh(existing)
            return existing

        # User does not exist, create a new user
        if provider and identifier:
            user = User(
                email=email,
                state=initial_state,
                external_logins=[
                    ExternalLogin(provider=provider, identifier=identifier)
                ],
                display_name=display_name,
            )
        else:
            user = User(email=email, state=initial_state, display_name=display_name)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "User":
        stmt = select(User).where(User.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_previous_ids_by_id(cls, session: AsyncSession, id: int) -> List[int]:
        result = await session.execute(
            select(user_merge_association.c.merged_user_id).where(
                user_merge_association.c.user_id == id
            )
        )
        merged_user_ids = result.scalars().all()
        return [user_id for user_id in merged_user_ids if user_id is not None]

    @classmethod
    async def get_all_by_id(cls, session: AsyncSession, ids: List[int]) -> List["User"]:
        if not ids:
            return []
        stmt = select(User).where(User.id.in_([int(id_) for id_ in ids]))
        result = await session.execute(stmt)
        return [row.User for row in result]

    @classmethod
    async def get_all_by_id_if_in_class(
        cls, session: AsyncSession, ids: List[int], class_id: int
    ) -> List["User"]:
        if not ids:
            return []

        stmt = (
            select(User)
            .join(UserClassRole)
            .where(
                User.id.in_([int(id_) for id_ in ids]),
                UserClassRole.class_id == class_id,
            )
        )

        result = await session.execute(stmt)
        return [row.User for row in result]

    @classmethod
    async def get_display_name(cls, session: AsyncSession, id_: int) -> str | None:
        stmt = select(User.display_name, User.first_name, User.last_name).where(
            User.id == int(id_)
        )
        response = await session.execute(stmt)
        result = response.first()
        if result:
            return result[0] or f"{result[1]} {result[2]}" or None
        return None


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
    Column("file_id", Integer, ForeignKey("files.id", ondelete="CASCADE")),
    Column("thread_id", Integer, ForeignKey("threads.id")),
    Index("code_interpreter_file_thread_idx", "file_id", "thread_id", unique=True),
)

image_file_thread_association = Table(
    "image_files_threads",
    Base.metadata,
    Column("file_id", Integer, ForeignKey("files.id")),
    Column("thread_id", Integer, ForeignKey("threads.id")),
    Index("image_file_thread_idx", "file_id", "thread_id", unique=True),
)

file_vector_store_association = Table(
    "file_vector_stores",
    Base.metadata,
    Column("file_id", Integer, ForeignKey("files.id", ondelete="CASCADE")),
    Column("vector_store_id", Integer, ForeignKey("vector_stores.id")),
    Index("file_vector_store_idx", "file_id", "vector_store_id", unique=True),
)


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    content_type = Column(String)
    file_id = Column(String)
    class_id = Column(Integer, ForeignKey("classes.id", ondelete="CASCADE"))
    uploader_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, default=None
    )
    private = Column(Boolean, default=False)
    class_ = relationship("Class", back_populates="files")
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
    threads_images = relationship(
        "Thread",
        secondary=image_file_thread_association,
        back_populates="image_files",
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
    async def get_by_file_id(cls, session: AsyncSession, file_id: str) -> "File":
        stmt = select(File).where(File.file_id == file_id)
        return await session.scalar(stmt)

    @classmethod
    async def delete(cls, session: AsyncSession, id_: int) -> None:
        stmt = delete(File).where(File.id == int(id_))
        await session.execute(stmt)

    @classmethod
    async def delete_by_file_id(cls, session: AsyncSession, file_id: str) -> None:
        stmt = delete(File).where(File.file_id == file_id)
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
    async def delete(cls, session: AsyncSession, id_: int) -> None:
        stmt = delete(file_vector_store_association).where(
            file_vector_store_association.c.vector_store_id == int(id_)
        )
        stmt_ = delete(VectorStore).where(VectorStore.id == int(id_))
        await session.execute(stmt)
        await session.execute(stmt_)

    @classmethod
    async def delete_return_file_ids(cls, session: AsyncSession, id_: int) -> List[int]:
        stmt = (
            delete(file_vector_store_association)
            .where(file_vector_store_association.c.vector_store_id == int(id_))
            .returning(file_vector_store_association.c.file_id)
        )

        stmt_ = delete(VectorStore).where(VectorStore.id == int(id_))
        result = await session.execute(stmt)
        file_ids = [row[0] for row in result.fetchall()]
        await session.execute(stmt_)
        return file_ids

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
    async def get_file_names_ids_by_id(
        cls, session: AsyncSession, id_: int
    ) -> dict[str, str]:
        stmt = select(VectorStore).where(VectorStore.id == int(id_))
        vector_store = await session.scalar(stmt)
        if not vector_store:
            return {}
        return {file.file_id: file.name for file in vector_store.files}

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

    @classmethod
    async def get_id_by_class_id(
        cls, session: AsyncSession, class_id: int
    ) -> AsyncGenerator[int, None]:
        stmt = select(VectorStore).where(VectorStore.class_id == int(class_id))
        result = await session.execute(stmt)
        for row in result:
            yield row.VectorStore.id


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
    temperature = Column(Float, server_default="1.0")
    class_id = Column(Integer, ForeignKey("classes.id"))
    class_ = relationship("Class", back_populates="assistants", foreign_keys=[class_id])
    threads = relationship("Thread", back_populates="assistant")
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
    async def get_by_id(cls, session: AsyncSession, id_: int | None) -> "Assistant":
        if not id_:
            return Assistant()
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
    async def async_get_by_class_id(
        cls, session: AsyncSession, class_id: int
    ) -> AsyncGenerator[int, None]:
        stmt = select(Assistant).where(Assistant.class_id == int(class_id))
        result = await session.execute(stmt)
        for row in result:
            yield row.Assistant.id

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

    @classmethod
    async def delete(cls, session: AsyncSession, id_: int) -> None:
        stmt = delete(Assistant).where(Assistant.id == int(id_))
        await session.execute(stmt)


class LMSClass(Base):
    __tablename__ = "lms_classes"
    __table_args__ = (
        UniqueConstraint("lms_id", "lms_tenant", "lms_type", name="_id_lms_uc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lms_id = Column(Integer, nullable=False)
    lms_tenant = Column(String, nullable=False)
    lms_type = Column(SQLEnum(schemas.LMSType), nullable=False)
    name = Column(String)
    course_code = Column(String)
    term = Column(String)
    classes = relationship("Class", back_populates="lms_class")

    @classmethod
    async def create_or_update(
        cls, session: AsyncSession, request: schemas.LMSClassRequest
    ) -> "LMSClass":
        stmt = (
            _get_upsert_stmt(session)(LMSClass)
            .values(
                name=request.name,
                term=request.term,
                course_code=request.course_code,
                lms_id=request.lms_id,
                lms_tenant=request.lms_tenant,
                lms_type=request.lms_type,
            )
            .on_conflict_do_update(
                index_elements=[
                    LMSClass.lms_id,
                    LMSClass.lms_tenant,
                    LMSClass.lms_type,
                ],
                set_=dict(
                    name=request.name,
                    term=request.term,
                    course_code=request.course_code,
                ),
            )
            .returning(LMSClass)
        )
        return await session.scalar(stmt)

    @classmethod
    async def delete_if_unused(cls, session: AsyncSession, id_: int) -> None:
        """Check if a Pingpong class is connected to this LMS class, delete otherwise."""
        stmt = select(Class).where(Class.lms_class_id == id_)
        lms_class = await session.scalar(stmt)

        if not lms_class:
            stmt_ = delete(LMSClass).where(LMSClass.id == id_)
            await session.execute(stmt_)


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String, nullable=True)
    provider = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    classes = relationship("Class", back_populates="api_key_obj")
    azure_endpoint = Column(String, nullable=True)
    azure_api_version = Column(String, nullable=True)
    available_as_default = Column(Boolean, default=False)
    azure_endpoint_coalesced = Column(
        String,
        Computed("COALESCE(azure_endpoint, '')"),
    )

    __table_args__ = (
        UniqueConstraint(
            "api_key",
            "provider",
            "azure_endpoint_coalesced",
            name="_key_endpoint_provider_uc",
        ),
    )

    @classmethod
    async def get_all_default_keys(cls, session: AsyncSession) -> List["APIKey"]:
        stmt = select(APIKey).where(APIKey.available_as_default.is_(True))
        result = await session.execute(stmt)
        return [row[0] for row in result]


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
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    api_key_obj = relationship("APIKey", back_populates="classes", lazy="selectin")
    private = Column(Boolean, default=False)
    lms_status = Column(SQLEnum(schemas.LMSStatus), default=schemas.LMSStatus.NONE)
    lms_class_id = Column(Integer, ForeignKey("lms_classes.id"), nullable=True)
    lms_class = relationship("LMSClass", back_populates="classes", lazy="selectin")
    lms_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    lms_user = relationship("User", back_populates="lms_syncs", lazy="selectin")
    lms_course_id = Column(Integer, nullable=True)
    lms_access_token = Column(String, nullable=True)
    lms_refresh_token = Column(String, nullable=True)
    lms_expires_in = Column(Integer, nullable=True)
    lms_token_added_at = Column(DateTime(timezone=True), nullable=True)
    lms_last_synced = Column(DateTime(timezone=True), nullable=True)
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
    last_rate_limited_at = Column(DateTime(timezone=True), nullable=True)

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
    async def get_api_key(
        cls, session: AsyncSession, id_: int
    ) -> schemas.APIKeyModelResponse:
        stmt = (
            select(Class)
            .options(joinedload(Class.api_key_obj))
            .where(Class.id == int(id_))
        )
        result = await session.scalar(stmt)
        return schemas.APIKeyModelResponse(
            api_key=result.api_key,
            api_key_obj=result.api_key_obj,
        )

    @classmethod
    async def update_api_key(
        cls,
        session: AsyncSession,
        id_: int,
        api_key: str,
        provider: str,
        azure_endpoint: str | None,
        azure_api_version: str | None,
        available_as_default: bool,
    ) -> "APIKey":
        stmt = (
            _get_upsert_stmt(session)(APIKey)
            .values(
                api_key=api_key,
                provider=provider,
                azure_endpoint=azure_endpoint,
                azure_api_version=azure_api_version,
                available_as_default=available_as_default,
            )
            .on_conflict_do_update(
                constraint="_key_endpoint_provider_uc",
                set_=dict(
                    azure_api_version=azure_api_version,
                    available_as_default=APIKey.available_as_default
                    or available_as_default,
                ),
            )
            .returning(APIKey)
        )
        api_key_obj = await session.scalar(stmt)

        stmt = (
            update(Class).where(Class.id == int(id_)).values(api_key_id=api_key_obj.id)
        )
        await session.execute(stmt)
        return api_key_obj

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
        update_data = data.dict(exclude_none=True)

        # Fetch the current state of the record
        existing_class = await cls.get_by_id(session, id_)

        if not existing_class:
            raise ValueError("Update failed: Group not found.")

        # If `private` is being updated to False, ensure it is currently public
        if (
            "private" in update_data
            and update_data["private"] is False
            and existing_class.private is True
        ):
            raise ValueError("Update failed: Cannot change a private group to public.")

        # Proceed with the update
        stmt = update(Class).where(Class.id == int(id_)).values(**update_data)
        await session.execute(stmt)

        return await cls.get_by_id(session, id_)

    @classmethod
    async def get_by_institution(
        cls, session: AsyncSession, institution_id: int
    ) -> List["Class"]:
        stmt = (
            select(Class)
            .options(joinedload(Class.institution))
            .options(joinedload(Class.lms_user))
            .where(Class.institution_id == int(institution_id))
        )
        result = await session.execute(stmt)
        return [row.Class for row in result]

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Class":
        stmt = (
            select(Class)
            .options(joinedload(Class.institution))
            .options(joinedload(Class.lms_user))
            .options(joinedload(Class.lms_class))
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
            .options(joinedload(Class.lms_user))
            .options(joinedload(Class.lms_class))
            .where(Class.id.in_(ids))
        )
        result = await session.execute(stmt)
        return [row.Class for row in result]

    @classmethod
    async def update_lms_token(
        cls,
        session: AsyncSession,
        class_id: int,
        access_token: str,
        expires_in: int,
        refresh_token: str | None = None,
        user_id: int | None = None,
        refresh: bool = False,
    ) -> None:
        """Update LMS authentication token. When refreshed, there's no need to provide a new refresh token; the same one can be reused."""
        stmt = (
            update(Class)
            .where(Class.id == class_id)
            .values(
                lms_access_token=access_token,
                lms_refresh_token=refresh_token
                if not refresh
                else Class.lms_refresh_token,
                lms_user_id=user_id if not refresh else Class.lms_user_id,
                lms_expires_in=expires_in,
                lms_status=schemas.LMSStatus.AUTHORIZED
                if not refresh
                else Class.lms_status,
                lms_token_added_at=func.now(),
            )
        )
        await session.execute(stmt)

    @classmethod
    async def mark_lms_sync_error(
        cls,
        session: AsyncSession,
        class_id: int,
    ) -> None:
        """Mark LMS class connection as errored out so user can be prompted to reauthenticate."""
        stmt = (
            update(Class)
            .where(Class.id == class_id)
            .values(lms_status=schemas.LMSStatus.ERROR)
        )
        await session.execute(stmt)

    @classmethod
    async def get_lms_token(
        cls, session: AsyncSession, class_id: int
    ) -> schemas.CanvasStoredAccessToken:
        """Return LMS token with DB time."""
        stmt = select(
            Class.lms_user_id,
            Class.lms_access_token,
            Class.lms_refresh_token,
            Class.lms_expires_in,
            Class.lms_token_added_at,
            func.now(),
        ).where(Class.id == class_id)
        response = await session.execute(stmt)
        result = response.first()
        return schemas.CanvasStoredAccessToken(
            user_id=result[0],
            access_token=result[1],
            refresh_token=result[2],
            expires_in=result[3],
            token_added_at=result[4],
            now=result[5],
        )

    @classmethod
    async def get_lms_course_id(
        cls, session: AsyncSession, class_id: int
    ) -> tuple["Class", datetime]:
        """Return LMS course ID with DB time."""
        stmt = (
            select(Class, func.now())
            .outerjoin(Class.lms_class)
            .options(contains_eager(Class.lms_class).load_only(LMSClass.lms_id))
            .where(Class.id == class_id)
        )
        result = await session.execute(stmt)
        return result.first()

    @classmethod
    async def dismiss_lms_sync(cls, session: AsyncSession, class_id: int) -> None:
        """Mark that a user has dismissed the LMS sync alert. Do not display moving forward."""
        stmt = (
            update(Class)
            .where(Class.id == class_id)
            .values(
                lms_status=schemas.LMSStatus.DISMISSED,
                lms_course_id=None,
                lms_access_token=None,
                lms_refresh_token=None,
                lms_expires_in=None,
                lms_token_added_at=None,
                lms_last_synced=None,
            )
        )
        await session.execute(stmt)

    @classmethod
    async def enable_lms_sync(cls, session: AsyncSession, class_id: int) -> None:
        """Mark that a user has re-enabled LMS Sync."""
        stmt = (
            update(Class)
            .where(Class.id == class_id)
            .values(lms_status=schemas.LMSStatus.NONE)
        )
        await session.execute(stmt)

    @classmethod
    async def update_lms_class(
        cls, session: AsyncSession, class_id: int, lms_id: int
    ) -> None:
        """Update the LMS linked Class ID."""
        stmt = select(Class).where(Class.id == class_id)
        class_instance = await session.scalar(stmt)

        if class_instance.lms_class_id and class_instance.lms_class_id != lms_id:
            old_lms_id = class_instance.lms_class_id
            class_instance.lms_class_id = lms_id
            class_instance.lms_last_synced = None
            await LMSClass.delete_if_unused(session, old_lms_id)
        else:
            class_instance.lms_class_id = lms_id

        class_instance.lms_status = schemas.LMSStatus.LINKED
        await session.flush()

    @classmethod
    async def update_last_synced(
        cls,
        session: AsyncSession,
        class_id: int,
    ) -> None:
        """Update the timestamp of when the class' roster was synced with LMS."""
        stmt = (
            update(Class)
            .where(Class.id == class_id)
            .values(lms_last_synced=func.now(), updated=Class.updated)
        )
        await session.execute(stmt)

    @classmethod
    async def get_all_to_sync(
        cls, session: AsyncSession, lms_tenant: str, lms_type: schemas.LMSType
    ) -> AsyncGenerator["Class", None]:
        """
        For syncing CRON job: Get all classes with an active
        LMS-linked class under a specific tenant.
        """
        stmt = (
            select(Class)
            .outerjoin(Class.lms_class)
            .options(
                contains_eager(Class.lms_class).load_only(
                    LMSClass.lms_tenant, LMSClass.lms_type
                )
            )
            .where(
                and_(
                    Class.lms_class_id is not None,
                    Class.lms_status == schemas.LMSStatus.LINKED,
                    LMSClass.lms_tenant == lms_tenant,
                    LMSClass.lms_type == lms_type,
                )
            )
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Class

    @classmethod
    async def remove_lms_sync(
        cls,
        session: AsyncSession,
        id_: int,
        lms_tenant: str,
        lms_type: schemas.LMSType,
        keep_users: bool = True,
        kill_connection: bool = False,
    ) -> list[int]:
        """Remove linked LMS class connection."""
        stmt = select(Class).where(Class.id == id_)
        class_instance = await session.scalar(stmt)

        if class_instance.lms_class_id:
            old_lms_class_id = class_instance.lms_class_id
            class_instance.lms_class_id = None
            class_instance.lms_status = schemas.LMSStatus.AUTHORIZED
            class_instance.lms_last_synced = None
            await LMSClass.delete_if_unused(session, old_lms_class_id)

        # Remove class AND LMS account connection
        if kill_connection:
            class_instance.lms_access_token = None
            class_instance.lms_refresh_token = None
            class_instance.lms_expires_in = None
            class_instance.lms_token_added_at = None
            class_instance.lms_status = schemas.LMSStatus.NONE

        user_ids = []
        if not keep_users:
            stmt_ = select(UserClassRole).where(
                and_(
                    UserClassRole.class_id == id_,
                    UserClassRole.lms_tenant == lms_tenant,
                    UserClassRole.lms_type == lms_type,
                )
            )
            result = await session.execute(stmt_)
            users = result.scalars().all()
            user_ids = [user.user_id for user in users]

            for user in users:
                await session.delete(user)
            await session.flush()
        else:
            stmt = (
                update(UserClassRole)
                .where(
                    and_(
                        UserClassRole.class_id == id_,
                        UserClassRole.lms_tenant == lms_tenant,
                        UserClassRole.lms_type == lms_type,
                    )
                )
                .values(lms_type=None, lms_tenant=None)
            )
            await session.execute(stmt)

        return user_ids

    @classmethod
    async def log_rate_limit_error(cls, session: AsyncSession, class_id: str) -> None:
        """Log the time of the last rate limit error."""
        stmt = (
            update(Class)
            .where(Class.id == int(class_id))
            .values(last_rate_limited_at=func.now())
        )
        await session.execute(stmt)

    async def delete(self, session: AsyncSession) -> None:
        self.institution = None
        stmt = delete(Class).where(Class.id == self.id)
        await session.execute(stmt)


class CodeInterpreterCall(Base):
    __tablename__ = "code_interpreter_calls"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, default=2)
    run_id = Column(String)
    step_id = Column(String, unique=True)
    thread_id = Column(Integer, ForeignKey("threads.id", ondelete="CASCADE"))
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
    ) -> AsyncGenerator["CodeInterpreterCall", None]:
        conditions = [
            CodeInterpreterCall.thread_id == thread_id,
            CodeInterpreterCall.created_at >= after,
        ]
        if before:
            conditions.append(CodeInterpreterCall.created_at <= before)
        stmt = select(CodeInterpreterCall).where(and_(*conditions))
        result = await session.execute(stmt)
        for row in result:
            yield row.CodeInterpreterCall


class Thread(Base):
    __tablename__ = "threads"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)
    version = Column(Integer, default=1)
    thread_id = Column(String, unique=True)
    class_id = Column(Integer, ForeignKey("classes.id"))
    class_ = relationship("Class", back_populates="threads", lazy="selectin")
    assistant_id = Column(Integer, ForeignKey("assistants.id"), index=True)
    assistant = relationship("Assistant", back_populates="threads", uselist=False)
    private = Column(Boolean)
    user_message_ct = Column(Integer, server_default="1")
    users = relationship(
        "User",
        secondary=user_thread_association,
        back_populates="threads",
        lazy="subquery",
    )
    image_files = relationship(
        "File",
        secondary=image_file_thread_association,
        back_populates="threads_images",
        lazy="selectin",
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
    last_activity = Column(
        DateTime(timezone=True), index=True, nullable=False, default=func.now()
    )
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
        image_file_ids = data.pop("image_file_ids", [])
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

        if image_file_ids:
            image_file_object_ids = await File.get_object_ids_by_file_id(
                session, image_file_ids
            )
            file_thread_pairs = [
                (obj_id, thread.id) for obj_id in image_file_object_ids
            ]
            stmt = (
                _get_upsert_stmt(session)(image_file_thread_association)
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
    async def get_ids_by_class_id(
        cls, session: AsyncSession, class_id: int
    ) -> AsyncGenerator["Thread", None]:
        stmt = select(Thread).where(Thread.class_id == int(class_id))
        result = await session.execute(stmt)
        for row in result:
            yield row.Thread

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
                if not next_latest_time or new_thread.last_activity < next_latest_time:
                    next_latest_time = new_thread.last_activity

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
            condition = and_(condition, Thread.last_activity < before)
        if class_id:
            condition = and_(condition, Thread.class_id == int(class_id))
        if private is not None:
            condition = and_(condition, Thread.private == private)

        stmt = (
            select(Thread)
            .outerjoin(Thread.assistant)
            .options(contains_eager(Thread.assistant).load_only(Assistant.name))
            .order_by(Thread.last_activity.desc())
            .where(condition)
            .limit(limit)
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
            condition = and_(condition, Thread.last_activity < before)
        stmt = (
            select(Thread)
            .order_by(Thread.last_activity.desc())
            .where(condition)
            .limit(limit)
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Thread

    @classmethod
    async def get_thread_by_class_id(
        cls,
        session: AsyncSession,
        class_id: int,
        desc: bool = True,
    ) -> AsyncGenerator["Thread", None]:
        stmt = (
            select(Thread)
            .outerjoin(Thread.users)
            .options(
                selectinload(Thread.users).load_only(User.id, User.created),
            )
            .order_by(Thread.updated.desc() if desc else Thread.updated.asc())
            .where(Thread.class_id == int(class_id))
        )
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
    async def update_tools_available(
        cls, session: AsyncSession, assistant_id: int, tools: str
    ) -> None:
        stmt = (
            update(Thread)
            .where(Thread.assistant_id == int(assistant_id))
            .values(tools_available=tools)
        )
        await session.execute(stmt)

    @classmethod
    async def add_image_files(
        cls, session: AsyncSession, thread_id: int, file_ids: list[str]
    ) -> None:
        if not file_ids:
            return
        image_file_object_ids = await File.get_object_ids_by_file_id(session, file_ids)
        image_file_thread_pairs = [
            (obj_id, thread_id) for obj_id in image_file_object_ids
        ]

        stmt = (
            _get_upsert_stmt(session)(image_file_thread_association)
            .values(image_file_thread_pairs)
            .on_conflict_do_nothing(
                index_elements=["file_id", "thread_id"],
            )
        )
        await session.execute(stmt)

    @classmethod
    async def get_file_search_files(
        cls, session: AsyncSession, thread_id: int
    ) -> dict[str, str]:
        stmt = (
            select(Thread)
            .outerjoin(Thread.assistant)
            .options(
                contains_eager(Thread.assistant).load_only(Assistant.vector_store_id)
            )
            .where(Thread.id == thread_id)
        )
        thread = await session.scalar(stmt)
        if not thread:
            return {}
        return await cls.get_file_search_files_by_thread(session, thread)

    @classmethod
    async def get_thread_components(
        cls, session: AsyncSession, thread_id: int
    ) -> tuple[Union["Assistant", None], dict[str, str], dict[str, "File"]]:
        stmt = (
            select(Thread)
            .options(joinedload(Thread.assistant))
            .where(Thread.id == thread_id)
        )
        thread = await session.scalar(stmt)

        if not thread:
            return None, {}, {}

        file_search_result, attachment_files = await asyncio.gather(
            cls.get_file_search_files_by_thread(session, thread),
            cls.get_thread_attachment_files(session, thread.id),
        )
        return thread.assistant, file_search_result or {}, attachment_files or {}

    @classmethod
    async def get_file_search_files_assistant(
        cls, session: AsyncSession, thread_id: int
    ) -> tuple[Union["Assistant", None], dict[str, str]]:
        stmt = (
            select(Thread)
            .options(joinedload(Thread.assistant))
            .where(Thread.id == thread_id)
        )
        thread = await session.scalar(stmt)

        if not thread:
            return None, {}

        return thread.assistant, await cls.get_file_search_files_by_thread(
            session, thread
        )

    @classmethod
    async def get_thread_attachment_files(
        cls, session: AsyncSession, id_: int
    ) -> dict[str, "File"]:
        stmt = (
            select(Thread)
            .options(joinedload(Thread.code_interpreter_files))
            .where(Thread.id == int(id_))
        )
        thread = await session.scalar(stmt)
        if not thread:
            return {}
        files_dict = await cls.get_code_interpreter_files_by_thread_id(
            session, thread.id
        )
        files_dict.update(
            await cls.get_vector_store_attachments_by_thread(session, thread)
        )
        return files_dict

    @classmethod
    async def get_vector_store_attachments_by_thread(
        cls, session: AsyncSession, thread: "Thread"
    ) -> dict[str, "File"]:
        if not thread.vector_store_id:
            return {}
        results = await VectorStore.get_files_by_id(session, thread.vector_store_id)
        return {file.file_id: file for file in results}

    @classmethod
    async def get_code_interpreter_files_by_thread_id(
        cls, session: AsyncSession, thread_id: int
    ) -> dict[str, "File"]:
        stmt = (
            select(File)
            .join(code_interpreter_file_thread_association)
            .where(code_interpreter_file_thread_association.c.thread_id == thread_id)
        )
        result = await session.execute(stmt)
        files = result.scalars().all()
        return {file.file_id: file for file in files}

    @classmethod
    async def get_file_search_files_by_thread(
        cls, session: AsyncSession, thread: "Thread"
    ) -> dict[str, str]:
        vector_store_ids: list[int] = []
        if thread.assistant and thread.assistant.vector_store_id:
            vector_store_ids.append(thread.assistant.vector_store_id)
        if thread.vector_store_id:
            vector_store_ids.append(thread.vector_store_id)
        if not vector_store_ids:
            return {}
        tasks = [
            VectorStore.get_file_names_ids_by_id(session, vector_store_id)
            for vector_store_id in vector_store_ids
        ]
        results = await asyncio.gather(*tasks)
        return {k: v for result in results for k, v in result.items()}
