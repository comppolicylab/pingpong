import asyncio
import json
from datetime import datetime
from typing import (
    AsyncGenerator,
    List,
    Literal,
    Optional,
    Union,
    Callable,
    Coroutine,
    Any,
)

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    UniqueConstraint,
    asc,
    desc,
    distinct,
    literal,
    literal_column,
    not_,
    or_,
    union_all,
)
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
from sqlalchemy.sql.elements import BinaryExpression
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
    defer,
)
from sqlalchemy.sql import func
import pingpong.schemas as schemas
import logging

logger = logging.getLogger(__name__)


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


class PeriodicTask(Base):
    __tablename__ = "periodic_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_name = Column(String)
    scheduled_jobs = relationship(
        "ScheduledJob",
        back_populates="task",
    )

    __table_args__ = (Index("idx_task_name", "task_name", unique=True),)

    @classmethod
    async def get_by_task_name(
        cls, session: AsyncSession, task_name: str
    ) -> "PeriodicTask":
        stmt = select(PeriodicTask).where(PeriodicTask.task_name == task_name)
        return await session.scalar(stmt)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("periodic_tasks.id", ondelete="cascade"), nullable=False
    )
    task = relationship("PeriodicTask", back_populates="scheduled_jobs")
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_task_id", "task_id"),)

    @classmethod
    async def get_latest_by_task_id(
        cls, session: AsyncSession, task_id: int
    ) -> "ScheduledJob":
        stmt = (
            select(ScheduledJob)
            .where(ScheduledJob.task_id == task_id)
            .order_by(ScheduledJob.scheduled_at.desc())
            .limit(1)
        )
        return await session.scalar(stmt)


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
    subscribed_to_summaries = Column(Boolean, server_default="true")
    last_summary_sent_at = Column(DateTime(timezone=True), nullable=True)
    last_summary_empty = Column(Boolean, server_default="false")

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
    async def get_by_user_ids(
        cls,
        session: AsyncSession,
        user_ids: List[int],
        class_id: int,
        subscribed_only: bool | None = None,
        sent_before: datetime | None = None,
    ) -> List["UserClassRole"]:
        conditions = [
            UserClassRole.user_id.in_(user_ids),
            UserClassRole.class_id == class_id,
        ]
        if subscribed_only:
            conditions.append(UserClassRole.subscribed_to_summaries.is_(True))
        if sent_before:
            conditions.append(
                or_(
                    UserClassRole.last_summary_sent_at.is_(None),
                    UserClassRole.last_summary_sent_at < sent_before,
                )
            )

        stmt = (
            select(UserClassRole)
            .options(joinedload(UserClassRole.user))
            .where(and_(*conditions))
        )
        result = await session.execute(stmt)
        return [row.UserClassRole for row in result]

    @classmethod
    async def mark_as_last_summary_empty(
        cls,
        session: AsyncSession,
        user_ids: List[int],
        class_id: int,
        subscribed_only: bool | None = None,
        sent_before: datetime | None = None,
    ):
        conditions = [
            UserClassRole.user_id.in_(user_ids),
            UserClassRole.class_id == class_id,
        ]
        if subscribed_only:
            conditions.append(UserClassRole.subscribed_to_summaries.is_(True))
        if sent_before:
            conditions.append(
                or_(
                    UserClassRole.last_summary_sent_at.is_(None),
                    UserClassRole.last_summary_sent_at < sent_before,
                )
            )

        stmt = (
            update(UserClassRole)
            .where(and_(*conditions))
            .values(last_summary_empty=True)
        )
        await session.execute(stmt)

    @classmethod
    async def is_subscribed_to_summaries(
        cls, session: AsyncSession, user_id: int, class_id: int
    ) -> bool:
        stmt = select(UserClassRole.subscribed_to_summaries).where(
            and_(UserClassRole.user_id == user_id, UserClassRole.class_id == class_id)
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_activity_summary_subscriptions(
        cls, session: AsyncSession, user_id: int, class_ids: List[int]
    ) -> schemas.ActivitySummarySubscriptions:
        stmt = (
            select(
                UserClassRole.class_id,
                Class.name,
                Class.private,
                UserClassRole.subscribed_to_summaries,
                UserClassRole.last_summary_sent_at,
                UserClassRole.last_summary_empty,
                or_(
                    Class.api_key.isnot(None),
                    Class.api_key_id.isnot(None),
                ).label("class_has_api_key"),
                User.dna_as_create,
                User.dna_as_join,
            )
            .join(Class, Class.id == UserClassRole.class_id)
            .join(User, User.id == UserClassRole.user_id)
            .where(
                and_(
                    UserClassRole.user_id == user_id,
                    UserClassRole.class_id.in_(class_ids),
                )
            )
        )
        result = await session.execute(stmt)
        rows = result.mappings().all()

        if not rows:
            return schemas.ActivitySummarySubscriptions(
                subscriptions=[],
                advanced_opts=schemas.ActivitySummarySubscriptionAdvancedOpts(
                    dna_as_create=False, dna_as_join=False
                ),
            )
        subscriptions = [
            schemas.ActivitySummarySubscription(
                class_id=row["class_id"],
                class_name=row["name"],
                class_private=row["private"],
                class_has_api_key=row["class_has_api_key"],
                subscribed=row["subscribed_to_summaries"],
                last_email_sent=row["last_summary_sent_at"],
                last_summary_empty=row["last_summary_empty"],
            )
            for row in rows
        ]
        opts = schemas.ActivitySummarySubscriptionAdvancedOpts(
            dna_as_create=rows[0]["dna_as_create"],
            dna_as_join=rows[0]["dna_as_join"],
        )
        return schemas.ActivitySummarySubscriptions(
            subscriptions=subscriptions, advanced_opts=opts
        )

    @classmethod
    async def subscribe_to_summaries(
        cls, session: AsyncSession, user_id: int, class_id: int
    ):
        stmt = (
            update(UserClassRole)
            .where(
                and_(
                    UserClassRole.user_id == user_id, UserClassRole.class_id == class_id
                )
            )
            .values(subscribed_to_summaries=True)
        )
        await session.execute(stmt)

    @classmethod
    async def unsubscribe_from_summaries(
        cls, session: AsyncSession, user_id: int, class_id: int
    ):
        stmt = (
            update(UserClassRole)
            .where(
                and_(
                    UserClassRole.user_id == user_id, UserClassRole.class_id == class_id
                )
            )
            .values(subscribed_to_summaries=False)
        )
        await session.execute(stmt)

    @classmethod
    async def unsubscribe_from_all_summaries(cls, session: AsyncSession, user_id: int):
        stmt = (
            update(UserClassRole)
            .where(UserClassRole.user_id == user_id)
            .values(subscribed_to_summaries=False)
        )
        await session.execute(stmt)

    @classmethod
    async def subscribe_to_all_summaries(cls, session: AsyncSession, user_id: int):
        stmt = (
            update(UserClassRole)
            .where(UserClassRole.user_id == user_id)
            .values(subscribed_to_summaries=True)
        )
        await session.execute(stmt)

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
        subscribed_to_summaries: bool = True,
    ) -> "UserClassRole":
        stmt = (
            _get_upsert_stmt(session)(UserClassRole)
            .values(
                user_id=int(user_id),
                class_id=int(class_id),
                lms_tenant=lms_tenant,
                lms_type=lms_type,
                subscribed_to_summaries=subscribed_to_summaries,
            )
            .on_conflict_do_update(
                index_elements=[UserClassRole.user_id, UserClassRole.class_id],
                set_=dict(
                    lms_tenant=lms_tenant,
                    lms_type=lms_type,
                    subscribed_to_summaries=(
                        subscribed_to_summaries or UserClassRole.subscribed_to_summaries
                    ),
                ),
            )
            .returning(UserClassRole)
        )
        result = await session.scalar(stmt)
        if sso_tenant and sso_id:
            logger.info(
                f"ELDEBUG: (UserClassRole.create) ExternalLogin RID before {sso_tenant}, {sso_id}, {user_id} creation: {await ExternalLogin.get_last_row_id(session)}"
            )
            await ExternalLogin.create_or_update(
                session, user_id, sso_tenant, sso_id, called_by="UserClassRole.create"
            )
            logger.info(
                f"ELDEBUG: (UserClassRole.create) ExternalLogin RID after {sso_tenant}, {sso_id}, {user_id} creation: {await ExternalLogin.get_last_row_id(session)}"
            )
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


agreement_policy_external_login_association = Table(
    "agreement_policies_external_logins",
    Base.metadata,
    Column("agreement_policy_id", Integer, ForeignKey("agreement_policies.id")),
    Column("provider_id", Integer, ForeignKey("external_login_providers.id")),
    Index(
        "agreement_policy_external_login_idx",
        "agreement_policy_id",
        "provider_id",
        unique=True,
    ),
)


class Agreement(Base):
    """
    Represents an Agreement that defines the terms provided to users. An
    Agreement includes an administrative name, and the HTML text of the agreement.
    May have multiple associated AgreementPolicy records.
    Once used by at least one AgreementPolicy, the Agreement should be read-only.

    Attributes:
      id (int): Unique identifier for the agreement.
      name (str): The administrative name of the agreement.
      body (str): The HTML content containing the text of the agreement.
      created (datetime): Timestamp when the agreement was first created.
      updated (datetime): Timestamp when the agreement was last updated.
    """

    __tablename__ = "agreements"

    id: Mapped[int] = mapped_column(primary_key=True)

    name = Column(String, nullable=False)
    body = Column(String, nullable=False)

    policies = relationship("AgreementPolicy", back_populates="agreement")
    acceptances = relationship("AgreementAcceptance", back_populates="agreement")

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Agreement":
        stmt = select(Agreement).where(Agreement.id == id_)
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id_with_policies(
        cls, session: AsyncSession, id_: int
    ) -> "Agreement":
        stmt = (
            select(Agreement)
            .where(Agreement.id == id_)
            .options(selectinload(Agreement.policies).load_only(AgreementPolicy.id))
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_all(cls, session: AsyncSession) -> list["Agreement"]:
        stmt = select(Agreement)
        result = await session.execute(stmt)
        return [row.Agreement for row in result]

    @classmethod
    async def get_by_policy_id(
        cls, session: AsyncSession, policy_id: int
    ) -> "Agreement":
        stmt = select(Agreement).where(
            Agreement.policies.any(AgreementPolicy.id == policy_id)
        )
        return await session.scalar(stmt)

    @classmethod
    async def create(
        cls, session: AsyncSession, data: schemas.CreateAgreementRequest
    ) -> "Agreement":
        agreement = Agreement(name=data.name, body=data.body)
        session.add(agreement)
        await session.flush()
        await session.refresh(agreement)
        return agreement


class AgreementPolicy(Base):
    """
    Represents a policy for an agreement. An AgreementPolicy defines when
    and under what conditions an agreement is applicable to users.

    Attributes:
      id (int): Unique identifier for the agreement policy.
      name (str): The unique name of the policy within an agreement.
      agreement_id (int): Foreign key that references the associated Agreement.
      agreement (Agreement): The related Agreement instance.
      not_before (datetime): Policy's start datetime - the policy does not apply before this time.
      not_after (datetime): Policy's expiry datetime - the policy does not apply after this time.
      apply_to_all (bool): Indicates if the policy applies universally to all users.
      limit_to_providers (List[ExternalLoginProvider]): A list of external login providers to which the policy is limited. The policy applies only to users with an ExternalLogin from at least one of these providers.
      created (datetime): Timestamp indicating when the policy was created.
      updated (datetime): Timestamp indicating when the policy was last updated.
    """

    __tablename__ = "agreement_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String, nullable=False)

    agreement_id: Mapped[int] = mapped_column(
        ForeignKey("agreements.id", ondelete="cascade"), nullable=False, index=True
    )
    agreement = relationship("Agreement", back_populates="policies")

    not_before = Column(DateTime(timezone=True), nullable=True)
    not_after = Column(DateTime(timezone=True), nullable=True)

    apply_to_all = Column(Boolean, default=False)
    limit_to_providers = relationship(
        "ExternalLoginProvider",
        secondary=agreement_policy_external_login_association,
        back_populates="agreement_policies",
    )

    acceptances = relationship("AgreementAcceptance", back_populates="policy")

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @staticmethod
    def eligibility_conditions(user_id: int) -> BinaryExpression[bool]:
        """
        Finds Agreement records that satisfy the following conditions:
        - The AgreementPolicy has a linked Agreement.
        - If the AgreementPolicy has a not_before or not_after time range, the current time must be in the allowed range.
        - There is no matching AgreementAcceptance record for the user for the Agreement ID.
        - The policy “applies” to the user, meaning that either:
            - its `apply_to_all` flag is True, or
            - if the policy is limited to a particular set of external login providers then the user must have at least one ExternalLogin with one of those providers.
        """
        return and_(
            AgreementPolicy.agreement_id.is_not(None),
            or_(
                AgreementPolicy.not_before.is_not(None),
                AgreementPolicy.not_before <= func.now(),
            ),
            or_(
                AgreementPolicy.not_after.is_(None),
                AgreementPolicy.not_after >= func.now(),
            ),
            not_(
                select(AgreementAcceptance.id)
                .where(
                    AgreementAcceptance.agreement_id == AgreementPolicy.agreement_id,
                    AgreementAcceptance.user_id == user_id,
                )
                .exists()
            ),
            or_(
                AgreementPolicy.apply_to_all,
                AgreementPolicy.limit_to_providers.any(
                    ExternalLoginProvider.external_logins.any(
                        ExternalLogin.user_id == user_id
                    )
                ),
            ),
        )

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "AgreementPolicy":
        stmt = select(AgreementPolicy).where(AgreementPolicy.id == id_)
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id_if_eligible(
        cls, session: AsyncSession, id_: int, user_id: int
    ) -> "AgreementPolicy":
        stmt = (
            select(AgreementPolicy)
            .where(AgreementPolicy.id == id_)
            .where(cls.eligibility_conditions(user_id))
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_all(cls, session: AsyncSession) -> list["AgreementPolicy"]:
        stmt = select(AgreementPolicy).options(
            selectinload(AgreementPolicy.agreement).load_only(
                Agreement.id, Agreement.name
            )
        )
        result = await session.execute(stmt)
        return [row.AgreementPolicy for row in result]

    @classmethod
    async def get_by_id_with_external_logins(
        cls, session: AsyncSession, id_: int
    ) -> "AgreementPolicy":
        stmt = (
            select(AgreementPolicy)
            .where(AgreementPolicy.id == id_)
            .options(
                selectinload(AgreementPolicy.limit_to_providers).load_only(
                    ExternalLoginProvider.id
                )
            )
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_pending_agreement_by_user_id(
        cls, session: AsyncSession, user_id: int
    ) -> int | None:
        """
        Returns the ID of the first pending Agreement for a user.

        Attributes:
            user_id (int): The ID of the user for whom to retrieve pending agreements.

        Returns:
            agreement_id (int | None): The ID of the first pending Agreement, or None if no pending agreements exist.

        Finds Agreement records that satisfy the following conditions:
        - If the AgreementPolicy has a not_before or not_after time range, the current time must be in the allowed range.
        - There is no matching AgreementAcceptance record for the user for the Agreement ID.
        - The policy “applies” to the user, meaning that either:
            - its `apply_to_all` flag is True, or
            - if the policy is limited to a particular set of external login providers then the user must have at least one ExternalLogin with one of those providers.

        Returns the ID of the first matching Agreement, or None if no such policy exists.
        """

        stmt = (
            select(AgreementPolicy.id)
            .where(*cls.eligibility_conditions(user_id))
            .order_by(AgreementPolicy.created.asc())
            .limit(1)
        )

        result = await session.scalar(stmt)
        return result


class AgreementAcceptance(Base):
    """
    Represents a user's acceptance of an agreement under a specific policy.

    Attributes:
      id (int): Unique identifier for the acceptance record.
      user_id (int): Foreign key referencing the user who accepted the agreement.
      agreement_id (int): Foreign key referencing the accepted Agreement.
      agreement (Agreement): The related Agreement instance.
      policy_id (int): Foreign key referencing the AgreementPolicy under which the agreement was accepted.
      policy (AgreementPolicy): The related AgreementPolicy instance.
      accepted_at (datetime): Timestamp when the user accepted the agreement.
    """

    __tablename__ = "agreement_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    user = relationship("User", back_populates="acceptances")

    agreement_id: Mapped[int] = mapped_column(
        ForeignKey("agreements.id"), nullable=False, index=True
    )
    agreement = relationship("Agreement", back_populates="acceptances")

    policy_id: Mapped[int] = mapped_column(
        ForeignKey("agreement_policies.id"), nullable=False, index=True
    )
    policy = relationship("AgreementPolicy", back_populates="acceptances")

    accepted_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "agreement_id", name="_user_agreement_uc"),
    )

    @classmethod
    async def accept_agreement(
        cls, session: AsyncSession, user_id: int, agreement_id: int, policy_id: int
    ) -> None:
        stmt = (
            _get_upsert_stmt(session)(AgreementAcceptance)
            .values(
                user_id=user_id,
                agreement_id=agreement_id,
                policy_id=policy_id,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "agreement_id"],
            )
        )
        return await session.scalar(stmt)


class ExternalLoginProvider(Base):
    __tablename__ = "external_login_providers"
    __table_args__ = (Index("ix_external_login_providers_name", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    icon = Column(String, nullable=True)
    external_logins: Mapped[List["ExternalLogin"]] = relationship(
        "ExternalLogin", back_populates="provider_obj"
    )
    agreement_policies: Mapped[List["AgreementPolicy"]] = relationship(
        "AgreementPolicy",
        secondary=agreement_policy_external_login_association,
        back_populates="limit_to_providers",
    )

    @classmethod
    async def get_by_name(
        cls, session: AsyncSession, name: str
    ) -> "ExternalLoginProvider":
        stmt = select(ExternalLoginProvider).where(ExternalLoginProvider.name == name)
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id(
        cls, session: AsyncSession, id_: int
    ) -> "ExternalLoginProvider":
        stmt = select(ExternalLoginProvider).where(ExternalLoginProvider.id == id_)
        return await session.scalar(stmt)

    @classmethod
    async def get_by_ids(
        cls, session: AsyncSession, ids: list[int]
    ) -> list["ExternalLoginProvider"]:
        stmt = select(ExternalLoginProvider).where(ExternalLoginProvider.id.in_(ids))
        result = await session.execute(stmt)
        return [row.ExternalLoginProvider for row in result]

    @classmethod
    async def get_or_create_by_name(
        cls,
        session: AsyncSession,
        name: str,
        display_name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
    ) -> "ExternalLoginProvider":
        existing = await cls.get_by_name(session, name)
        if existing:
            return existing
        provider = ExternalLoginProvider(
            name=name, description=description, display_name=display_name, icon=icon
        )
        session.add(provider)
        await session.flush()
        await session.refresh(provider)
        return provider

    @classmethod
    async def get_all(cls, session: AsyncSession) -> list["ExternalLoginProvider"]:
        stmt = select(ExternalLoginProvider)
        result = await session.execute(stmt)
        return [row.ExternalLoginProvider for row in result]


class ExternalLogin(Base):
    __tablename__ = "external_logins"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="external_logins")
    provider_id = Column(
        Integer, ForeignKey("external_login_providers.id"), nullable=True
    )
    provider_obj = relationship(
        "ExternalLoginProvider", back_populates="external_logins"
    )
    provider = Column(String, nullable=False)
    identifier = Column(String, nullable=False)

    # Add an index to help with lookups
    __table_args__ = (
        Index("idx_user_provider", "user_id", "provider"),
        Index("idx_user_provider_id", "user_id", "provider_id"),
        UniqueConstraint(
            "user_id", "provider", "identifier", name="uq_user_provider_identifier"
        ),
        UniqueConstraint(
            "user_id",
            "provider_id",
            "identifier",
            name="uq_user_provider_id_identifier",
        ),
    )

    @classmethod
    async def get_last_row_id(cls, session: AsyncSession) -> int | None:
        stmt = select(func.max(ExternalLogin.id))
        result = await session.scalar(stmt)
        return result

    @classmethod
    async def create_or_update(
        cls,
        session: AsyncSession,
        user_id: int,
        provider: str,
        identifier: str,
        called_by: str | None = None,
    ) -> bool:
        provider_ = await ExternalLoginProvider.get_or_create_by_name(session, provider)
        if provider not in {"email"}:
            # For other providers, first check if a record exists
            stmt = select(ExternalLogin).where(
                and_(
                    ExternalLogin.user_id == user_id,
                    or_(
                        ExternalLogin.provider == provider,
                        ExternalLogin.provider_id == provider_.id,
                    ),
                )
            )
            existing = await session.scalar(stmt)

            if existing:
                existing.identifier = identifier
                session.add(existing)
                await session.flush()
                return True
            else:
                new_login = ExternalLogin(
                    user_id=user_id,
                    provider=provider,
                    identifier=identifier,
                    provider_id=provider_.id,
                )
                session.add(new_login)
                await session.flush()
                if called_by:
                    logger.info(
                        f"ELDEBUG: ({called_by}) Creating new external login for user {user_id} with provider {provider} and identifier {identifier}"
                    )
                return True
        else:
            # For email provider, always create a new record if it doesn't exist
            # and it's not being used by another user. This allows multiple
            # 'email' provider identifiers for the same user.
            email_to_add = identifier.lower().strip()
            conflicting_user = await User.get_by_email_sso(
                session, identifier, "email", email_to_add
            )
            if conflicting_user and conflicting_user.id != user_id:
                raise ValueError(f"Email {email_to_add} is already in use.")

            # Do not add a duplicate record for the same user
            stmt = (
                _get_upsert_stmt(session)(ExternalLogin)
                .values(
                    user_id=user_id,
                    provider=provider,
                    provider_id=provider_.id,
                    identifier=email_to_add,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "provider", "identifier"],
                    set_=dict(provider_id=provider_.id, provider=provider),
                )
            )
            result = await session.execute(stmt)
            return result.rowcount > 0

    @classmethod
    async def accounts_to_merge(
        cls, session: AsyncSession, user_id: int, provider: str, identifier: str
    ) -> list[int]:
        stmt_ = (
            select(ExternalLogin.user_id)
            .join(ExternalLoginProvider)
            .where(
                and_(
                    or_(
                        ExternalLogin.provider == provider,
                        ExternalLoginProvider.name == provider,
                    ),
                    ExternalLogin.identifier == identifier,
                    ExternalLogin.user_id != user_id,
                )
            )
        )
        result = await session.execute(stmt_)
        return list(set(row[0] for row in result))

    @classmethod
    async def get_secondary_emails_by_user_id(
        cls, session: AsyncSession, user_id: int
    ) -> list["ExternalLogin"]:
        stmt = (
            select(ExternalLogin)
            .join(ExternalLoginProvider)
            .where(
                and_(
                    ExternalLogin.user_id == user_id,
                    or_(
                        ExternalLogin.provider == "email",
                        ExternalLoginProvider.name == "email",
                    ),
                )
            )
        )
        result = await session.execute(stmt)
        return [row.ExternalLogin for row in result]

    @classmethod
    async def delete_secondary_email(
        cls, session: AsyncSession, user_id: int, email: str
    ) -> None:
        result = await session.execute(
            delete(ExternalLogin)
            .join(ExternalLoginProvider)
            .where(
                and_(
                    ExternalLogin.user_id == user_id,
                    or_(
                        ExternalLogin.provider == "email",
                        ExternalLoginProvider.name == "email",
                    ),
                    ExternalLogin.identifier == email,
                )
            )
        )
        if result.rowcount == 0:
            raise ValueError(f"No secondary email {email} found for user {user_id}")
        return None

    @classmethod
    async def get_all_providers(cls, session: AsyncSession) -> list[str]:
        stmt = select(ExternalLogin.provider).distinct()
        result = await session.execute(stmt)
        return [row[0] for row in result]

    @classmethod
    async def migrate_provider_by_name(
        cls, session: AsyncSession, provider: str
    ) -> None:
        provider_ = await ExternalLoginProvider.get_or_create_by_name(session, provider)
        stmt = (
            update(ExternalLogin)
            .where(
                ExternalLogin.provider == provider, ExternalLogin.provider_id.is_(None)
            )
            .values(provider_id=provider_.id)
        )
        await session.execute(stmt)

    @classmethod
    async def missing_provider_ids(
        cls, session: AsyncSession
    ) -> AsyncGenerator["ExternalLogin", None]:
        stmt = select(ExternalLogin).where(ExternalLogin.provider_id.is_(None))
        for row in await session.execute(stmt):
            yield row.ExternalLogin


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
    classes: Mapped[List["UserClassRole"]] = relationship(back_populates="user")
    institutions: Mapped[List["UserInstitutionRole"]] = relationship(
        back_populates="user"
    )
    assistants: Mapped[List["Assistant"]] = relationship(
        "Assistant", back_populates="creator"
    )
    super_admin = Column(Boolean, default=False)
    threads = relationship(
        "Thread", secondary=user_thread_association, back_populates="users"
    )
    external_logins: Mapped[List["ExternalLogin"]] = relationship(
        "ExternalLogin", back_populates="user"
    )
    # Maps to classes in which the user has connected their LMS account
    lms_syncs: Mapped[List["Class"]] = relationship("Class", back_populates="lms_user")
    anonymous_link_id = Column(Integer, ForeignKey("anonymous_links.id"), nullable=True)
    anonymous_link = relationship("AnonymousLink", back_populates="user", uselist=False)
    anonymous_sessions = relationship("AnonymousSession", back_populates="user")
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())
    # Do Not Add - Activity Summaries - Groups I Join
    dna_as_join = Column(Boolean, server_default="false")
    # Do Not Add - Activity Summaries - Groups I Create
    dna_as_create = Column(Boolean, server_default="false")
    acceptances = relationship("AgreementAcceptance", back_populates="user")

    @classmethod
    async def create_anonymous_user(
        cls, session: AsyncSession, anonymous_link_id: int
    ) -> "User":
        user = User(anonymous_link_id=anonymous_link_id)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user

    @classmethod
    async def update_info(
        self, session: AsyncSession, user_id: int, data: schemas.UpdateUserInfo
    ) -> "User":
        data_dict = data.model_dump(exclude_none=True)
        stmt = update(User).where(User.id == int(user_id)).values(**data_dict)
        await session.execute(stmt)
        return await User.get_by_id(session, user_id)

    @classmethod
    async def update_dna_as_create(
        cls, session: AsyncSession, user_id: int, value: bool
    ) -> None:
        stmt = update(User).where(User.id == user_id).values(dna_as_create=value)
        await session.execute(stmt)

    @classmethod
    async def update_dna_as_join(
        cls, session: AsyncSession, user_id: int, value: bool
    ) -> None:
        stmt = update(User).where(User.id == user_id).values(dna_as_join=value)
        await session.execute(stmt)

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
            .join(ExternalLoginProvider)
            .where(
                and_(
                    or_(
                        ExternalLogin.provider == provider,
                        ExternalLoginProvider.name == provider,
                    ),
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
                logger.info(
                    f"ELDEBUG: (User.get_or_create_by_email_sso) ExternalLogin RID before adding {provider}, {identifier}, {existing.id}: {await ExternalLogin.get_last_row_id(session)}"
                )

                # We might not have the external login information stored
                await ExternalLogin.create_or_update(
                    session,
                    existing.id,
                    provider=provider,
                    identifier=identifier,
                    called_by="User.get_or_create_by_email_sso",
                )

            # Now that we updated the external login, we can return the user
            await session.refresh(existing)
            if provider and identifier:
                logger.info(
                    f"ELDEBUG: (User.get_or_create_by_email_sso, EXISTING user) ExternalLogin RID after adding {provider}, {identifier}, {existing.id}: {await ExternalLogin.get_last_row_id(session)}"
                )
            return existing

        # User does not exist, create a new user
        if provider and identifier:
            logger.info(
                f"ELDEBUG: (User.get_or_create_by_email_sso, NEW user) ExternalLogin RID before adding {provider}, {identifier}: {await ExternalLogin.get_last_row_id(session)}"
            )
            provider_ = await ExternalLoginProvider.get_or_create_by_name(
                session, provider
            )
            user = User(
                email=email,
                state=initial_state,
                external_logins=[
                    ExternalLogin(
                        provider=provider,
                        identifier=identifier,
                        provider_id=provider_.id,
                    )
                ],
                display_name=display_name,
            )
        else:
            user = User(email=email, state=initial_state, display_name=display_name)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        if provider and identifier:
            logger.info(
                f"ELDEBUG: (User.get_or_create_by_email_sso, NEW user) ExternalLogin RID before adding {provider}, {identifier}, {user.id}: {await ExternalLogin.get_last_row_id(session)}"
            )
        return user

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "User":
        stmt = select(User).where(User.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_external_logins_by_id(
        cls, session: AsyncSession, id_: int
    ) -> List["ExternalLogin"]:
        stmt = (
            select(ExternalLogin)
            .where(ExternalLogin.user_id == int(id_))
            .options(selectinload(ExternalLogin.provider_obj))
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    @classmethod
    async def get_by_share_token(
        cls, session: AsyncSession, share_token: str
    ) -> "User":
        stmt = (
            select(User)
            .join(AnonymousLink)
            .options(selectinload(User.anonymous_link))
            .where(AnonymousLink.share_token == share_token)
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_by_session_token(
        cls, session: AsyncSession, session_token: str
    ) -> tuple["User", "AnonymousSession"] | tuple[None, None]:
        stmt = (
            select(User, AnonymousSession)
            .join(AnonymousSession)
            .options(selectinload(User.anonymous_link))
            .where(AnonymousSession.session_token == session_token)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row:
            return row[0], row[1]
        else:
            return None, None

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

    @classmethod
    async def get_by_emails_check_external_logins(
        cls, session: AsyncSession, emails: List[str]
    ) -> List[int]:
        if not emails:
            return []
        lower_emails = [email.lower() for email in emails]
        stmt = (
            select(User.id)
            .outerjoin(ExternalLogin)
            .outerjoin(
                ExternalLoginProvider,
                ExternalLogin.provider_id == ExternalLoginProvider.id,
            )
            .where(
                or_(
                    func.lower(User.email).in_(lower_emails),
                    and_(
                        func.lower(ExternalLogin.identifier).in_(lower_emails),
                        or_(
                            ExternalLogin.provider == "email",
                            ExternalLoginProvider.name == "email",
                        ),
                    ),
                )
            )
        )
        result = await session.execute(stmt)
        return [row[0] for row in result]


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

file_class_association = Table(
    "file_classes",
    Base.metadata,
    Column("file_id", Integer, ForeignKey("files.id", ondelete="CASCADE")),
    Column("class_id", Integer, ForeignKey("classes.id", ondelete="CASCADE")),
    Index("file_class_idx", "file_id", "class_id", unique=True),
)

file_search_attachment_association = Table(
    "message_attachments_file_search",
    Base.metadata,
    Column("message_id", Integer, ForeignKey("messages.id", ondelete="CASCADE")),
    Column("file_id", Integer, ForeignKey("files.id", ondelete="CASCADE")),
    Index("message_attachments_file_search_idx", "message_id", "file_id", unique=True),
)

code_interpreter_attachment_association = Table(
    "message_attachments_code_interpreter",
    Base.metadata,
    Column("message_id", Integer, ForeignKey("messages.id", ondelete="CASCADE")),
    Column("file_id", Integer, ForeignKey("files.id", ondelete="CASCADE")),
    Index(
        "message_attachments_code_interpreter_idx", "message_id", "file_id", unique=True
    ),
)

assistant_link_association = Table(
    "assistant_anonymous_links",
    Base.metadata,
    Column("assistant_id", Integer, ForeignKey("assistants.id", ondelete="CASCADE")),
    Column("link_id", Integer, ForeignKey("anonymous_links.id", ondelete="CASCADE")),
    Index("assistant_link_idx", "assistant_id", "link_id", unique=True),
)


class S3File(Base):
    __tablename__ = "s3_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    key = Column(String, nullable=False, unique=True)
    files = relationship("File", back_populates="s3_file")
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        key: str,
        file_obj_ids: list[int] | None = None,
        file_ids: list[str] | None = None,
    ) -> "S3File":
        s3_file = S3File(key=key)
        session.add(s3_file)
        await session.flush()
        await session.refresh(s3_file)

        stmt = (
            update(File)
            .where(or_(File.id.in_(file_obj_ids), File.file_id.in_(file_ids)))
            .values(s3_file_id=s3_file.id)
        )
        await session.execute(stmt)
        return s3_file

    @classmethod
    async def get_s3_files_without_files(
        cls, session: AsyncSession
    ) -> AsyncGenerator["S3File", None]:
        """Returns an async generator of S3Files that are not linked to any File."""
        stmt = (
            select(S3File)
            .outerjoin(File, S3File.id == File.s3_file_id)
            .where(File.id.is_(None))
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.S3File


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    content_type = Column(String)
    file_id = Column(String)
    class_id = Column(Integer, ForeignKey("classes.id"))
    uploader_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, default=None
    )
    private = Column(Boolean, default=False)
    s3_file_id = Column(
        Integer,
        ForeignKey("s3_files.id", ondelete="SET NULL", name="fk_files_s3_files"),
        nullable=True,
    )
    s3_file = relationship("S3File", uselist=False)
    class_ = relationship("Class", back_populates="files")
    classes = relationship(
        "Class", secondary=file_class_association, back_populates="files"
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
    threads_images = relationship(
        "Thread",
        secondary=image_file_thread_association,
        back_populates="image_files",
    )
    input_images = relationship(
        "MessagePart",
        back_populates="input_image_file",
    )
    message_attachments_file_search = relationship(
        "Message",
        secondary=file_search_attachment_association,
        back_populates="file_search_attachments",
    )
    message_attachments_code_interpreter = relationship(
        "Message",
        secondary=code_interpreter_attachment_association,
        back_populates="code_interpreter_attachments",
    )
    anonymous_session_id = Column(
        Integer, ForeignKey("anonymous_sessions.id", ondelete="CASCADE"), nullable=True
    )
    anonymous_session = relationship(
        "AnonymousSession",
        back_populates="files",
        uselist=False,
    )
    anonymous_link_id = Column(
        Integer, ForeignKey("anonymous_links.id", ondelete="SET NULL"), nullable=True
    )
    anonymous_link = relationship(
        "AnonymousLink",
        back_populates="files",
        uselist=False,
    )

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def get_all_generator(
        cls, session: AsyncSession
    ) -> AsyncGenerator["File", None]:
        """Returns an async generator of all shared files in the database."""
        stmt = select(File).where(File.private.is_(False))
        result = await session.execute(stmt)
        for row in result:
            yield row.File

    @classmethod
    async def create(cls, session: AsyncSession, data: dict, class_id: int) -> "File":
        file = File(**data)
        session.add(file)
        await session.flush()
        await session.refresh(file)
        stmt = (
            _get_upsert_stmt(session)(file_class_association)
            .values(class_id=class_id, file_id=file.id)
            .on_conflict_do_nothing(
                index_elements=["file_id", "class_id"],
            )
        )
        await session.execute(stmt)
        return file

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "File":
        stmt = select(File).where(File.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id_with_download(cls, session: AsyncSession, id_: int) -> "File":
        stmt = (
            select(File).where(File.id == int(id_)).options(selectinload(File.s3_file))
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_by_file_id(cls, session: AsyncSession, file_id: str) -> "File":
        stmt = select(File).where(File.file_id == file_id)
        return await session.scalar(stmt)

    @classmethod
    async def get_obj_id_by_file_id(cls, session: AsyncSession, file_id: str) -> "File":
        stmt = select(File.id).where(File.file_id == file_id)
        return await session.scalar(stmt)

    @classmethod
    async def delete(cls, session: AsyncSession, id_: int) -> None:
        stmt = delete(File).where(File.id == int(id_))
        await session.execute(stmt)

    @classmethod
    async def delete_multiple(
        cls, session: AsyncSession, ids: list[int]
    ) -> tuple[list["File"], list[int]]:
        if not ids:
            return [], []

        stmt = delete(File).where(File.id.in_(ids)).returning(File)
        result = await session.execute(stmt)

        deleted_rows = result.fetchall()
        deleted_files = [row[0] for row in deleted_rows]
        deleted_obj_ids = {row[0].id for row in deleted_rows}
        missing_ids = list(set(ids) - deleted_obj_ids)

        return deleted_files, missing_ids

    @classmethod
    async def delete_by_file_id(cls, session: AsyncSession, file_id: str) -> None:
        stmt = delete(File).where(File.file_id == file_id)
        await session.execute(stmt)

    @classmethod
    async def get_all_by_ids_if_exist(
        cls, session: AsyncSession, ids: list[int]
    ) -> List["File"]:
        if not ids:
            return []
        stmt = select(File).where(File.id.in_(ids))
        result = await session.execute(stmt)
        return [row.File for row in result]

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

    @classmethod
    async def assistant_count_using_file(
        cls, session: AsyncSession, id_: int, class_id: int
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Assistant)
            .join(
                code_interpreter_file_assistant_association,
                code_interpreter_file_assistant_association.c.assistant_id
                == Assistant.id,
                isouter=True,
            )
            .join(
                VectorStore, VectorStore.id == Assistant.vector_store_id, isouter=True
            )
            .join(
                file_vector_store_association,
                file_vector_store_association.c.vector_store_id == VectorStore.id,
                isouter=True,
            )
            .where(
                or_(
                    file_vector_store_association.c.file_id == id_,
                    code_interpreter_file_assistant_association.c.file_id == id_,
                )
            )
            .where(Assistant.class_id == class_id)
        )
        return await session.scalar(stmt)

    @classmethod
    async def assistant_count_using_files(
        cls, session: AsyncSession, ids: list[int], class_id: int
    ) -> List[tuple[int, int]]:
        vs_path = (
            select(
                file_vector_store_association.c.file_id.label("file_id"),
                Assistant.id.label("assistant_id"),
            )
            .join(
                VectorStore,
                file_vector_store_association.c.vector_store_id == VectorStore.id,
            )
            .join(Assistant, Assistant.vector_store_id == VectorStore.id)
            .where(
                file_vector_store_association.c.file_id.in_(ids),
                Assistant.class_id == class_id,
            )
        )

        ci_path = (
            select(
                code_interpreter_file_assistant_association.c.file_id.label("file_id"),
                Assistant.id.label("assistant_id"),
            )
            .join(
                Assistant,
                code_interpreter_file_assistant_association.c.assistant_id
                == Assistant.id,
            )
            .where(
                code_interpreter_file_assistant_association.c.file_id.in_(ids),
                Assistant.class_id == class_id,
            )
        )

        files_and_assistants = union_all(vs_path, ci_path).subquery()

        stmt = select(
            files_and_assistants.c.file_id,
            func.count(distinct(files_and_assistants.c.assistant_id)),
        ).group_by(files_and_assistants.c.file_id)
        result = await session.execute(stmt)
        return result.all()

    @classmethod
    async def get_files_not_used_by_assistant(
        cls, session: AsyncSession, assistant_id: int, file_ids: list[int]
    ) -> list[int]:
        if not file_ids:
            return []

        vs_path = (
            select(file_vector_store_association.c.file_id.label("file_id"))
            .join(
                VectorStore,
                file_vector_store_association.c.vector_store_id == VectorStore.id,
            )
            .join(Assistant, Assistant.vector_store_id == VectorStore.id)
            .where(
                Assistant.id == assistant_id,
                file_vector_store_association.c.file_id.in_(file_ids),
            )
        )
        ci_path = (
            select(
                code_interpreter_file_assistant_association.c.file_id.label("file_id")
            )
            .join(
                Assistant,
                Assistant.id
                == code_interpreter_file_assistant_association.c.assistant_id,
            )
            .where(
                Assistant.id == assistant_id,
                code_interpreter_file_assistant_association.c.file_id.in_(file_ids),
            )
        )
        files_and_assistants = union_all(vs_path, ci_path).subquery()

        # Get the file IDs that ARE used by the assistant
        stmt = select(files_and_assistants.c.file_id).distinct()
        result = await session.execute(stmt)
        used_file_ids = {row[0] for row in result}

        # Return file IDs that are NOT used by the assistant
        return [file_id for file_id in file_ids if file_id not in used_file_ids]

    @classmethod
    async def remove_file_from_class(
        cls, session: AsyncSession, file_id: int, class_id: int
    ) -> None:
        stmt = delete(file_class_association).where(
            file_class_association.c.class_id == class_id,
            file_class_association.c.file_id == file_id,
        )
        await session.execute(stmt)

    @classmethod
    async def remove_files_from_class(
        cls, session: AsyncSession, file_ids: List[int], class_id: int
    ) -> None:
        if not file_ids:
            return
        stmt = delete(file_class_association).where(
            file_class_association.c.class_id == class_id,
            file_class_association.c.file_id.in_(file_ids),
        )
        await session.execute(stmt)

    @classmethod
    async def class_count_using_file(cls, session: AsyncSession, id_: int) -> int:
        stmt = (
            select(func.count())
            .select_from(file_class_association)
            .where(file_class_association.c.file_id == id_)
        )
        return await session.scalar(stmt)

    @classmethod
    async def class_count_using_files(
        cls, session: AsyncSession, ids: list[int]
    ) -> List[tuple[int, int]]:
        if not ids:
            return []
        stmt = (
            select(file_class_association.c.file_id, func.count())
            .group_by(file_class_association.c.file_id)
            .select_from(file_class_association)
            .where(file_class_association.c.file_id.in_(ids))
        )
        result = await session.execute(stmt)
        return result.all()

    @classmethod
    async def add_files_to_class(
        cls, session: AsyncSession, class_id: int, file_ids: list[int]
    ) -> None:
        if not file_ids:
            return
        file_class_pairs = [(file_id, class_id) for file_id in file_ids]

        stmt = (
            _get_upsert_stmt(session)(file_class_association)
            .values(file_class_pairs)
            .on_conflict_do_nothing(
                index_elements=["file_id", "class_id"],
            )
        )
        await session.execute(stmt)


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
        stmt = (
            select(VectorStore)
            .where(VectorStore.id == int(id_))
            .options(selectinload(VectorStore.files))
        )
        vector_store = await session.scalar(stmt)
        if not vector_store:
            return []
        return vector_store.files

    @classmethod
    async def get_file_obj_ids_by_id(cls, session: AsyncSession, id_: int) -> List[str]:
        stmt = (
            select(VectorStore)
            .where(VectorStore.id == int(id_))
            .options(selectinload(VectorStore.files))
        )
        vector_store = await session.scalar(stmt)
        if not vector_store:
            return []
        return [file.file_id for file in vector_store.files]

    @classmethod
    async def get_file_ids_by_id(
        cls, session: AsyncSession, id_: int
    ) -> AsyncGenerator[tuple[str, int], None]:
        stmt = (
            select(VectorStore)
            .where(VectorStore.id == int(id_))
            .options(selectinload(VectorStore.files))
        )
        vector_store = await session.scalar(stmt)
        if not vector_store:
            return
        for file in vector_store.files:
            yield file.file_id, file.id

    @classmethod
    async def get_file_names_ids_by_id(
        cls, session: AsyncSession, id_: int
    ) -> dict[str, str]:
        stmt = (
            select(VectorStore)
            .where(VectorStore.id == int(id_))
            .options(selectinload(VectorStore.files))
        )
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

        vector_store = await cls.get_by_id(session, vector_store_obj_id)
        if not vector_store:
            raise ValueError(
                f"Vector store with id {vector_store_obj_id} does not exist."
            )

        if len(current_file_ids) - len(file_ids_to_remove) + len(file_ids_to_add) > 100:
            raise ValueError(
                "The number of files in the vector store exceeds the limit of 100."
            )
        vector_store_id = vector_store.vector_store_id

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

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "VectorStore":
        stmt = select(VectorStore).where(VectorStore.id == int(id_))
        return await session.scalar(stmt)


class AnonymousLink(Base):
    __tablename__ = "anonymous_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String, nullable=True)
    share_token = Column(String, unique=True, nullable=False)
    assistant = relationship(
        "Assistant",
        secondary=assistant_link_association,
        back_populates="anonymous_links",
        uselist=False,
    )
    user = relationship("User", back_populates="anonymous_link")
    files = relationship(
        "File",
        back_populates="anonymous_link",
    )
    active = Column(Boolean, default=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        share_token: str,
        assistant_id: int,
    ) -> "AnonymousLink":
        link = AnonymousLink(
            share_token=share_token, active=True, activated_at=func.now()
        )
        session.add(link)
        await session.flush()
        await session.refresh(link)

        stmt = (
            _get_upsert_stmt(session)(assistant_link_association)
            .values(assistant_id=assistant_id, link_id=link.id)
            .on_conflict_do_nothing(
                index_elements=["assistant_id", "link_id"],
            )
        )
        await session.execute(stmt)
        return link

    @classmethod
    async def get_by_assistant_id(
        cls, session: AsyncSession, assistant_id: int
    ) -> List["AnonymousLink"]:
        stmt = (
            select(AnonymousLink)
            .join(assistant_link_association)
            .where(assistant_link_association.c.assistant_id == assistant_id)
        )
        result = await session.execute(stmt)
        return [row.AnonymousLink for row in result]

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "AnonymousLink":
        stmt = select(AnonymousLink).where(AnonymousLink.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def revoke(cls, session: AsyncSession, id_: int) -> "AnonymousLink":
        stmt = (
            update(AnonymousLink)
            .where(AnonymousLink.id == int(id_))
            .values(active=False, revoked_at=func.now())
            .returning(AnonymousLink)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class Assistant(Base):
    __tablename__ = "assistants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    version = Column(Integer, default=1)
    instructions = Column(String)
    interaction_mode = Column(
        SQLEnum(schemas.InteractionMode),
        server_default=schemas.InteractionMode.CHAT.name,
    )
    description = Column(String)
    assistant_id = Column(String)
    use_latex = Column(Boolean)
    use_image_descriptions = Column(Boolean)
    hide_prompt = Column(Boolean, default=False)
    locked = Column(Boolean, server_default="false")
    tools = Column(String)
    model = Column(String)
    temperature = Column(Float, nullable=True)
    reasoning_effort = Column(Integer, nullable=True)
    verbosity = Column(Integer, nullable=True)
    assistant_should_message_first = Column(Boolean, server_default="false")
    should_record_user_information = Column(Boolean, server_default="false")
    class_id = Column(Integer, ForeignKey("classes.id"))
    class_ = relationship("Class", back_populates="assistants", foreign_keys=[class_id])
    threads = relationship("Thread", back_populates="assistant")
    code_interpreter_files = relationship(
        "File",
        secondary=code_interpreter_file_assistant_association,
        back_populates="assistants_v2",
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
    anonymous_links = relationship(
        "AnonymousLink",
        secondary=assistant_link_association,
        back_populates="assistant",
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
    async def get_by_id_with_ci_files(
        cls, session: AsyncSession, id_: int | None
    ) -> "Assistant":
        if not id_:
            return Assistant()
        stmt = (
            select(Assistant)
            .where(Assistant.id == int(id_))
            .options(selectinload(Assistant.code_interpreter_files))
        )
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
        stmt = select(Assistant.id).where(Assistant.class_id == int(class_id))
        result = await session.execute(stmt)
        for row in result:
            yield row.id

    @classmethod
    async def async_get_id_name_by_class_id(
        cls, session: AsyncSession, class_id: int, version: int | None = None
    ) -> AsyncGenerator[tuple[int, str], None]:
        stmt = select(Assistant.id, Assistant.name).where(
            Assistant.class_id == int(class_id)
        )
        if version is not None:
            stmt = stmt.where(Assistant.version == version)
        result = await session.execute(stmt)
        for row in result:
            yield row.id, row.name

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
        assistant_id: str | None = None,
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
        params["use_image_descriptions"] = data.use_image_descriptions
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

    @classmethod
    async def get_count_by_model(cls, session: AsyncSession) -> list[tuple[str, int]]:
        stmt = select(Assistant.model, func.count(Assistant.id)).group_by(
            Assistant.model
        )
        result = await session.execute(stmt)
        return result.all()

    @classmethod
    async def get_by_model_with_stats(
        cls, session: AsyncSession, model: str
    ) -> List["Assistant"]:
        stmt = (
            select(
                Assistant.id,
                Assistant.name,
                Assistant.class_id,
                Assistant.updated,
                Assistant.created,
                func.max(Thread.last_activity).label("last_activity"),
                Class.name.label("class_name"),
            )
            .outerjoin(Assistant.threads)
            .join(Assistant.class_)
            .where(Assistant.model == model)
            .group_by(
                Assistant.id,
                Assistant.class_id,
                Assistant.updated,
                Assistant.created,
                Class.name,
            )
        )
        result = await session.execute(stmt)
        return result.all()

    @classmethod
    async def get_by_model(cls, session: AsyncSession, model: str) -> List["Assistant"]:
        stmt = select(Assistant).where(Assistant.model == model)
        result = await session.execute(stmt)
        return [row.Assistant for row in result]

    @classmethod
    async def get_by_class_id_models(
        cls, session: AsyncSession, class_id: int, models: list[str]
    ) -> AsyncGenerator["Assistant", None]:
        stmt = select(Assistant).where(
            and_(
                Assistant.class_id == class_id,
                Assistant.model.in_(models),
            )
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Assistant

    @classmethod
    async def async_get_published(
        cls,
        session: AsyncSession,
        class_id: int,
        user_ids: list[int] | None = None,
        version: int | None = None,
    ) -> AsyncGenerator["Assistant", None]:
        condition = [Assistant.published.is_not(None)]
        if user_ids:
            condition.append(Assistant.creator_id.in_(user_ids))
        if version:
            condition.append(Assistant.version == version)

        stmt = (
            select(Assistant)
            .where(
                and_(
                    Assistant.class_id == class_id,
                    *condition,
                )
            )
            .options(selectinload(Assistant.code_interpreter_files))
        )

        result = await session.execute(stmt)

        for row in result:
            yield row.Assistant

    @classmethod
    async def copy_code_interpreter_files(
        cls, session: AsyncSession, old_assistant_id: int, new_assistant_id: int
    ) -> None:
        """Copy code interpreter files from one API key to another."""
        source_rows = select(
            code_interpreter_file_assistant_association.c.file_id,
            literal(new_assistant_id).label("assistant_id"),
        ).where(
            code_interpreter_file_assistant_association.c.assistant_id
            == old_assistant_id
        )

        stmt = (
            _get_upsert_stmt(session)(code_interpreter_file_assistant_association)
            .from_select(["file_id", "assistant_id"], source_rows)
            .on_conflict_do_nothing(
                index_elements=["file_id", "assistant_id"],
            )
        )
        await session.execute(stmt)

    @classmethod
    async def get_code_interpreter_file_obj_ids_by_assistant_id(
        cls, session: AsyncSession, assistant_id: int
    ) -> list[str]:
        stmt = (
            select(File.file_id)
            .join(code_interpreter_file_assistant_association)
            .where(
                code_interpreter_file_assistant_association.c.assistant_id
                == assistant_id
            )
        )
        result = await session.execute(stmt)
        return [row[0] for row in result]

    @classmethod
    async def update_all_assistants_private_class(
        cls, session: AsyncSession, class_id: int
    ) -> None:
        stmt = (
            update(Assistant)
            .where(Assistant.class_id == class_id)
            .values(should_record_user_information=False)
        )
        await session.execute(stmt)

    @classmethod
    async def get_all_assistants_by_version(
        cls, session: AsyncSession, version: int
    ) -> AsyncGenerator["Assistant", None]:
        """Get all assistants by version."""
        stmt = select(Assistant).where(Assistant.version == version)
        result = await session.execute(stmt)
        for assistant in result:
            yield assistant.Assistant

    @classmethod
    async def get_all_openai_assistants_by_version_and_interaction_mode(
        cls,
        session: AsyncSession,
        version: int,
        interaction_mode: schemas.InteractionMode,
    ) -> AsyncGenerator["Assistant", None]:
        """Get all assistants by version and interaction mode."""
        stmt = (
            select(Assistant)
            .join(Assistant.class_)
            .outerjoin(Class.api_key_obj)
            .where(
                and_(
                    Assistant.version == version,
                    Assistant.interaction_mode == interaction_mode,
                    or_(
                        APIKey.provider == "openai",
                        Class.api_key.is_not(None),
                    ),
                )
            )
        )
        result = await session.execute(stmt)
        for assistant in result:
            yield assistant.Assistant


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
    __table_args__ = (
        UniqueConstraint(
            "api_key",
            "provider",
            name="_key_provider_uc",
        ),
        Index("api_key_available_as_default_idx", "available_as_default"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String, nullable=True)
    provider = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    classes = relationship("Class", back_populates="api_key_obj")
    endpoint = Column(String, nullable=True)
    api_version = Column(String, nullable=True)
    region = Column(String, nullable=True)
    available_as_default = Column(Boolean, default=False)

    @classmethod
    async def create_or_update(
        cls,
        session: AsyncSession,
        api_key: str,
        provider: str,
        endpoint: str | None = None,
        api_version: str | None = None,
        region: str | None = None,
        available_as_default: bool = False,
    ) -> "APIKey":
        stmt = (
            _get_upsert_stmt(session)(APIKey)
            .values(
                api_key=api_key,
                provider=provider,
                endpoint=endpoint,
                api_version=api_version,
                region=region,
                available_as_default=available_as_default,
            )
            .on_conflict_do_update(
                constraint="_key_provider_uc",
                set_=dict(
                    api_version=api_version,
                    region=region,
                    available_as_default=APIKey.available_as_default
                    or available_as_default,
                ),
            )
            .returning(APIKey)
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_all_default_keys(cls, session: AsyncSession) -> List["APIKey"]:
        stmt = select(APIKey).where(APIKey.available_as_default.is_(True))
        result = await session.execute(stmt)
        return [row[0] for row in result]

    @classmethod
    async def get_azure_keys_with_no_region_info(
        cls, session: AsyncSession
    ) -> AsyncGenerator["APIKey", None]:
        """Get all Azure keys with no region info."""
        stmt = (
            select(APIKey)
            .where(APIKey.provider == "azure")
            .where(APIKey.region.is_(None))
        )
        result = await session.execute(stmt)
        for row in result:
            yield row[0]


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name = Column(String)
    institution_id = Column(Integer, ForeignKey("institutions.id"))
    institution = relationship("Institution", back_populates="classes")
    assistants: Mapped[List["Assistant"]] = relationship(
        "Assistant",
        back_populates="class_",
    )
    term = Column(String)
    api_key = Column(String, nullable=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True)
    api_key_obj = relationship("APIKey", back_populates="classes")
    private = Column(Boolean, default=False)
    lms_status = Column(SQLEnum(schemas.LMSStatus), default=schemas.LMSStatus.NONE)
    lms_tenant = Column(String, nullable=True)
    lms_type = Column(SQLEnum(schemas.LMSType), nullable=True)
    lms_class_id = Column(Integer, ForeignKey("lms_classes.id"), nullable=True)
    lms_class = relationship("LMSClass", back_populates="classes")
    lms_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    lms_user = relationship("User", back_populates="lms_syncs")
    lms_course_id = Column(Integer, nullable=True)
    lms_access_token = Column(String, nullable=True)
    lms_refresh_token = Column(String, nullable=True)
    lms_expires_in = Column(Integer, nullable=True)
    lms_token_added_at = Column(DateTime(timezone=True), nullable=True)
    lms_last_synced = Column(DateTime(timezone=True), nullable=True)
    any_can_create_assistant = Column(Boolean, default=False)
    any_can_publish_assistant = Column(Boolean, default=False)
    any_can_share_assistant = Column(Boolean, default=False)
    any_can_publish_thread = Column(Boolean, default=False)
    any_can_upload_class_file = Column(Boolean, default=False)
    users: Mapped[List["UserClassRole"]] = relationship(
        "UserClassRole",
        back_populates="class_",
    )
    files = relationship(
        "File",
        secondary=file_class_association,
        back_populates="classes",
    )
    threads = relationship("Thread", back_populates="class_")
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(DateTime(timezone=True), index=True, onupdate=func.now())
    last_rate_limited_at = Column(DateTime(timezone=True), nullable=True)
    last_summary_sent_at = Column(DateTime(timezone=True), nullable=True)

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
        endpoint: str | None,
        api_version: str | None,
        region: str | None,
        available_as_default: bool,
    ) -> "APIKey":
        api_key_obj = await APIKey.create_or_update(
            session,
            api_key=api_key,
            provider=provider,
            endpoint=endpoint,
            api_version=api_version,
            region=region,
            available_as_default=available_as_default,
        )

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

        if (
            "private" in update_data
            and update_data["private"] is True
            and existing_class.private is False
        ):
            # If changing to private, ensure no assistants are set to record user information
            await Assistant.update_all_assistants_private_class(session, id_)

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
            .options(joinedload(Class.api_key_obj))
            .where(Class.id == int(id_))
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_by_ids(
        cls,
        session: AsyncSession,
        ids: List[int],
        exclude_private: bool = False,
        with_api_key: bool = False,
    ) -> AsyncGenerator["Class", None]:
        if not ids:
            return

        conditions = [Class.id.in_(ids)]
        if exclude_private:
            conditions.append(Class.private.is_(False))
        if with_api_key:
            conditions.append(
                or_(Class.api_key_id.isnot(None), Class.api_key.isnot(None))
            )
        stmt = select(Class).where(and_(*conditions))
        result = await session.execute(stmt)
        for row in result:
            yield row.Class

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
        lms_tenant: str | None = None,
        lms_type: schemas.LMSType | None = None,
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
                lms_tenant=lms_tenant if lms_tenant is not None else Class.lms_tenant,
                lms_type=lms_type if lms_type is not None else Class.lms_type,
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
                lms_user_id=None,
                lms_tenant=None,
                lms_type=None,
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
        cls,
        session: AsyncSession,
        class_id: int,
        lms_id: int,
        tenant: str,
        lms_type: schemas.LMSType,
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
        class_instance.lms_tenant = tenant
        class_instance.lms_type = lms_type
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
    async def get_linked_courses_with_no_tenant_info(
        cls,
        session: AsyncSession,
    ) -> AsyncGenerator["Class", None]:
        """Return linked courses with no tenant information."""
        stmt = select(Class).where(
            and_(
                Class.lms_status != schemas.LMSStatus.NONE,
                Class.lms_tenant.is_(None),
            )
        )
        result = await session.execute(stmt)
        for row in result.scalars():
            yield row

    @classmethod
    async def get_linked_courses_with_no_lms_type_info(
        cls,
        session: AsyncSession,
    ) -> AsyncGenerator["Class", None]:
        """Return linked courses with no LMS type information."""
        stmt = select(Class).where(
            and_(
                Class.lms_status != schemas.LMSStatus.NONE,
                Class.lms_type.is_(None),
            )
        )
        result = await session.execute(stmt)
        for row in result.scalars():
            yield row

    @classmethod
    async def get_all_to_sync(
        cls,
        session: AsyncSession,
        lms_tenant: str,
        lms_type: schemas.LMSType,
        sync_classes_with_error_status: bool = False,
    ) -> AsyncGenerator["Class", None]:
        """
        For syncing CRON job: Get all classes with an active
        LMS-linked class under a specific tenant.
        """
        lms_status_condition = (
            or_(
                Class.lms_status == schemas.LMSStatus.LINKED,
                Class.lms_status == schemas.LMSStatus.ERROR,
            )
            if sync_classes_with_error_status
            else Class.lms_status == schemas.LMSStatus.LINKED
        )
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
                    LMSClass.lms_tenant == lms_tenant,
                    LMSClass.lms_type == lms_type,
                    lms_status_condition,
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
            class_instance.lms_tenant = None
            class_instance.lms_type = None
            class_instance.lms_user_id = None

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

    @classmethod
    async def clear_rate_limit_logs(
        cls,
        session: AsyncSession,
        after: DateTime | None = None,
        before: DateTime | None = None,
    ) -> None:
        """Clear rate limit logs for classes."""
        conditions: list[BinaryExpression[bool]] = []
        conditions.append(Class.last_rate_limited_at.isnot(None))
        if after:
            conditions.append(Class.last_rate_limited_at > after)
        if before:
            conditions.append(Class.last_rate_limited_at < before)

        stmt = update(Class).where(and_(*conditions)).values(last_rate_limited_at=None)
        await session.execute(stmt)

    @classmethod
    async def get_all_classes_to_summarize(
        cls, session: AsyncSession, before: datetime | None = None
    ) -> AsyncGenerator["Class", None]:
        """Get all classes that need summarization."""
        conditions = [
            Class.private.is_(False),
            or_(
                Class.api_key_id.isnot(None),
                Class.api_key.isnot(None),
            ),
        ]
        if before:
            conditions.append(
                or_(
                    Class.last_summary_sent_at < before,
                    Class.last_summary_sent_at.is_(None),
                ),
            )
        stmt = select(Class).where(and_(*conditions))
        result = await session.execute(stmt)

        for row in result:
            yield row.Class

    @classmethod
    async def get_all_classes_with_api_keys(
        cls, session: AsyncSession, before: datetime | None = None
    ) -> AsyncGenerator["Class", None]:
        """Get all classes that have API keys."""
        stmt = select(Class).where(
            or_(
                Class.api_key_id.isnot(None),
                Class.api_key.isnot(None),
            )
        )
        result = await session.execute(stmt)

        for row in result:
            yield row.Class

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


class VoiceModeRecording(Base):
    __tablename__ = "voice_mode_recordings"

    id = Column(Integer, primary_key=True)
    thread_id = Column(Integer, ForeignKey("threads.id", ondelete="CASCADE"))
    thread = relationship(
        "Thread", back_populates="voice_mode_recording", uselist=False
    )
    recording_id = Column(String, unique=True)
    duration = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "VoiceModeRecording":
        recording = VoiceModeRecording(**data)
        session.add(recording)
        await session.flush()
        return recording

    @classmethod
    async def delete(cls, session: AsyncSession, id_: int) -> None:
        stmt = delete(VoiceModeRecording).where(VoiceModeRecording.id == id_)
        await session.execute(stmt)

    @classmethod
    async def get_all_gen(
        cls, session: AsyncSession
    ) -> AsyncGenerator["VoiceModeRecording", None]:
        # Select all recordings
        # Load thread relationship eagerly
        # In threads, load the full class_ relationship eagerly
        stmt = select(VoiceModeRecording).options(
            joinedload(VoiceModeRecording.thread).joinedload(Thread.class_)
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.VoiceModeRecording


class AnonymousSession(Base):
    __tablename__ = "anonymous_sessions"

    id = Column(Integer, primary_key=True)
    session_token = Column(String, unique=True, nullable=False)
    thread_id = Column(
        Integer, ForeignKey("threads.id", ondelete="cascade"), nullable=True
    )
    thread = relationship("Thread", back_populates="anonymous_sessions", uselist=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="cascade"), nullable=True)
    user = relationship("User", back_populates="anonymous_sessions", uselist=False)
    files = relationship(
        "File",
        back_populates="anonymous_session",
    )
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        session_token: str,
        thread_id: int | None = None,
        user_id: int | None = None,
    ) -> "AnonymousSession":
        session_obj = AnonymousSession(
            session_token=session_token,
            thread_id=thread_id,
            user_id=user_id,
        )
        session.add(session_obj)
        await session.flush()

        stmt = (
            select(AnonymousSession)
            .where(AnonymousSession.id == session_obj.id)
            .options(
                joinedload(AnonymousSession.user),
            )
        )

        result = await session.execute(stmt)
        return result.scalars().first()


class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True)
    type = Column(SQLEnum(schemas.AnnotationType), nullable=False)

    message_part_id = Column(
        Integer, ForeignKey("message_parts.id", ondelete="CASCADE"), nullable=False
    )
    message_part = relationship(
        "MessagePart", back_populates="annotations", uselist=False
    )
    annotation_index = Column(Integer, nullable=False)

    file_id = Column(String, nullable=True)
    file_object_id = Column(
        Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )

    vision_file_id = Column(String, nullable=True)
    vision_file_object_id = Column(
        Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )

    container_id = Column(String, nullable=True)

    filename = Column(String, nullable=True)
    title = Column(String, nullable=True)
    url = Column(String, nullable=True)
    text = Column(String, nullable=True)

    index = Column(Integer, nullable=True)
    start_index = Column(Integer, nullable=True)
    end_index = Column(Integer, nullable=True)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> None:
        annotation = Annotation(**data)
        session.add(annotation)
        await session.flush()


class WebSearchCallSearchSource(Base):
    __tablename__ = "web_search_call_search_sources"

    id = Column(Integer, primary_key=True)

    web_search_call_action_id = Column(
        Integer,
        ForeignKey("web_search_call_actions.id", ondelete="CASCADE"),
        nullable=False,
    )
    web_search_call_action = relationship(
        "WebSearchCallAction", back_populates="sources", uselist=False
    )
    tool_call_id = Column(
        Integer, ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )

    url = Column(String, nullable=True)
    name = Column(String, nullable=True)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> None:
        source = cls(**data)
        session.add(source)
        await session.flush()


class WebSearchCallAction(Base):
    __tablename__ = "web_search_call_actions"

    id = Column(Integer, primary_key=True)

    type = Column(SQLEnum(schemas.WebSearchActionType), nullable=False)

    tool_call_id = Column(
        Integer, ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )
    tool_call = relationship(
        "ToolCall", back_populates="web_search_actions", uselist=False
    )

    query = Column(String, nullable=True)
    url = Column(String, nullable=True)
    pattern = Column(String, nullable=True)

    sources = relationship(
        "WebSearchCallSearchSource",
        back_populates="web_search_call_action",
    )

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "WebSearchCallAction":
        result = cls(**data)
        session.add(result)
        await session.flush()
        return result


class FileSearchCallResult(Base):
    __tablename__ = "file_search_call_results"

    id = Column(Integer, primary_key=True)

    attributes = Column(String, nullable=True)
    file_id = Column(String, nullable=True)
    file_object_id = Column(
        Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    filename = Column(String, nullable=True)

    tool_call_id = Column(
        Integer, ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )
    tool_call = relationship("ToolCall", back_populates="results", uselist=False)

    score = Column(Float, nullable=True)
    text = Column(String, nullable=True)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> None:
        result = cls(**data)
        session.add(result)
        await session.flush()


class CodeInterpreterCallOutput(Base):
    __tablename__ = "code_interpreter_call_outputs"

    id = Column(Integer, primary_key=True)
    tool_call_id = Column(
        Integer, ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )
    tool_call = relationship("ToolCall", back_populates="outputs", uselist=False)

    output_type = Column(SQLEnum(schemas.CodeInterpreterOutputType), nullable=False)
    logs = Column(String, nullable=True)
    url = Column(String, nullable=True)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> None:
        output = cls(**data)
        session.add(output)
        await session.flush()


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(Integer, primary_key=True)
    tool_call_id = Column(String, nullable=False)

    type = Column(SQLEnum(schemas.ToolCallType), nullable=False)
    status = Column(SQLEnum(schemas.ToolCallStatus), nullable=False)

    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    run = relationship("Run", back_populates="tool_calls", uselist=False)

    thread_id = Column(
        Integer, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    thread = relationship("Thread", back_populates="tool_calls", uselist=False)

    output_index = Column(Integer, nullable=False)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed = Column(DateTime(timezone=True), nullable=True)

    queries = Column(String, nullable=True)
    results = relationship("FileSearchCallResult", back_populates="tool_call")

    code = Column(String, nullable=True)
    container_id = Column(String, nullable=True)
    outputs = relationship(
        "CodeInterpreterCallOutput",
        back_populates="tool_call",
    )

    web_search_actions = relationship("WebSearchCallAction", back_populates="tool_call")

    @classmethod
    async def mark_as_incomplete(cls, session: AsyncSession, id: int) -> None:
        """Mark a tool call as incomplete."""
        stmt = (
            update(ToolCall)
            .where(ToolCall.id == id)
            .values(status=schemas.ToolCallStatus.INCOMPLETE)
        )
        await session.execute(stmt)

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "ToolCall":
        """Create a new tool call."""
        tool_call = cls(**data)
        session.add(tool_call)
        await session.flush()
        return tool_call

    @classmethod
    async def update_status(
        cls,
        session: AsyncSession,
        id: int,
        status: schemas.ToolCallStatus,
        completed: datetime | None = None,
    ) -> None:
        """Update the status of a tool call."""
        stmt = (
            update(ToolCall)
            .where(ToolCall.id == id)
            .values(status=status, completed=completed)
        )
        await session.execute(stmt)

    @classmethod
    async def add_code_delta(
        cls, session: AsyncSession, id: int, code_delta: str
    ) -> None:
        """Append a code delta to a tool call."""
        stmt = (
            update(ToolCall)
            .where(ToolCall.id == id)
            .values(code=ToolCall.code + code_delta)
        )
        await session.execute(stmt)

    @classmethod
    async def add_status_queries(
        cls,
        session: AsyncSession,
        id: int,
        status: schemas.ToolCallStatus,
        queries: str,
    ) -> None:
        """Append status queries to a tool call."""
        stmt = (
            update(ToolCall)
            .where(ToolCall.id == id)
            .values(queries=queries, status=status)
        )
        await session.execute(stmt)


class ReasoningSummaryPart(Base):
    __tablename__ = "reasoning_summary_parts"

    id = Column(Integer, primary_key=True)

    reasoning_step_id = Column(
        Integer, ForeignKey("reasoning_steps.id", ondelete="CASCADE"), nullable=False
    )
    reasoning_step = relationship(
        "ReasoningStep", back_populates="summary_parts", uselist=False
    )

    part_index = Column(Integer, nullable=False)

    summary_text = Column(String, nullable=True)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "ReasoningSummaryPart":
        summary_part = cls(**data)
        session.add(summary_part)
        await session.flush()
        return summary_part

    @classmethod
    async def add_summary_text_delta(
        cls, session: AsyncSession, id: int, delta: str
    ) -> None:
        """Append a summary text delta to a reasoning summary part."""
        stmt = (
            update(ReasoningSummaryPart)
            .where(ReasoningSummaryPart.id == id)
            .values(summary_text=ReasoningSummaryPart.summary_text + delta)
        )
        await session.execute(stmt)


class ReasoningContentPart(Base):
    __tablename__ = "reasoning_content_parts"

    id = Column(Integer, primary_key=True)

    reasoning_step_id = Column(
        Integer, ForeignKey("reasoning_steps.id", ondelete="CASCADE"), nullable=False
    )
    reasoning_step = relationship(
        "ReasoningStep", back_populates="content_parts", uselist=False
    )

    part_index = Column(Integer, nullable=False)

    content_text = Column(String, nullable=True)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> None:
        content_part = cls(**data)
        session.add(content_part)
        await session.flush()


class ReasoningStep(Base):
    __tablename__ = "reasoning_steps"

    id = Column(Integer, primary_key=True)
    reasoning_id = Column(String, nullable=True)

    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    run = relationship("Run", back_populates="reasoning_steps", uselist=False)

    thread_id = Column(
        Integer, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    thread = relationship("Thread", back_populates="reasoning_steps", uselist=False)

    output_index = Column(Integer, nullable=False)

    summary_parts = relationship(
        "ReasoningSummaryPart",
        back_populates="reasoning_step",
    )
    content_parts = relationship(
        "ReasoningContentPart",
        back_populates="reasoning_step",
    )
    encrypted_content = Column(String, nullable=True)

    status = Column(SQLEnum(schemas.ReasoningStatus), nullable=False)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed = Column(DateTime(timezone=True), nullable=True)

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "ReasoningStep":
        reasoning_step = cls(**data)
        session.add(reasoning_step)
        await session.flush()
        return reasoning_step

    @classmethod
    async def mark_as_incomplete(cls, session: AsyncSession, id: int) -> None:
        """Mark a reasoning step as incomplete."""
        stmt = (
            update(ReasoningStep)
            .where(ReasoningStep.id == id)
            .values(status=schemas.ReasoningStatus.INCOMPLETE)
        )
        await session.execute(stmt)

    @classmethod
    async def mark_status(
        cls,
        session: AsyncSession,
        id: int,
        status: schemas.ReasoningStatus,
        encrypted_content: str | None = None,
    ) -> None:
        """Mark a reasoning step as a specific status."""
        stmt = (
            update(ReasoningStep)
            .where(ReasoningStep.id == id)
            .values(
                status=status,
                encrypted_content=encrypted_content
                if encrypted_content is not None
                else ReasoningStep.encrypted_content,
            )
        )
        await session.execute(stmt)

    @classmethod
    async def update_encrypted_content(
        cls,
        session: AsyncSession,
        reasoning_id: str,
        encrypted_content: str,
    ) -> None:
        """Update the encrypted content of a reasoning step."""
        stmt = (
            update(ReasoningStep)
            .where(ReasoningStep.reasoning_id == reasoning_id)
            .values(encrypted_content=encrypted_content)
        )
        await session.execute(stmt)


class MessagePart(Base):
    __tablename__ = "message_parts"

    id = Column(Integer, primary_key=True)
    type = Column(SQLEnum(schemas.MessagePartType), nullable=False)

    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"))
    message = relationship("Message", back_populates="content", uselist=False)

    part_index = Column(Integer, nullable=False)

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    text = Column(String, nullable=True)
    input_image_file_id = Column(String, nullable=True)
    input_image_file_object_id = Column(
        Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    input_image_file = relationship(
        "File", back_populates="input_images", uselist=False
    )

    refusal = Column(String, nullable=True)

    annotations = relationship(
        "Annotation",
        back_populates="message_part",
    )

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "MessagePart":
        """Create a new message part."""
        message_part = cls(**data)
        session.add(message_part)
        await session.flush()
        return message_part

    @classmethod
    async def add_text_delta(
        cls, session: AsyncSession, id_: int, text_delta: str
    ) -> None:
        """Append a text delta to a message part."""
        stmt = (
            update(MessagePart)
            .where(MessagePart.id == id_)
            .values(text=MessagePart.text + text_delta)
        )
        await session.execute(stmt)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    message_id = Column(String, nullable=True)
    message_status = Column(SQLEnum(schemas.MessageStatus), nullable=False)

    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    run = relationship("Run", back_populates="messages", uselist=False)

    thread_id = Column(
        Integer, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    thread = relationship("Thread", back_populates="messages", uselist=False)

    assistant_id = Column(
        Integer, ForeignKey("assistants.id", ondelete="SET NULL"), nullable=True
    )

    output_index = Column(Integer, nullable=False)

    role = Column(SQLEnum(schemas.MessageRole), nullable=False)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    file_search_attachments = relationship(
        "File",
        secondary=file_search_attachment_association,
        back_populates="message_attachments_file_search",
    )

    code_interpreter_attachments = relationship(
        "File",
        secondary=code_interpreter_attachment_association,
        back_populates="message_attachments_code_interpreter",
    )

    content = relationship(
        "MessagePart",
        back_populates="message",
    )

    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed = Column(DateTime(timezone=True), nullable=True)

    @classmethod
    async def get_messages_by_thread_id(
        cls, session: AsyncSession, thread_id: int
    ) -> AsyncGenerator["Message", None]:
        stmt = (
            select(Message)
            .join(Run)
            .filter(Run.thread_id == thread_id)
            .order_by(Message.created.desc())
        )

        result = await session.execute(stmt)
        for row in result:
            yield row.Message

    @classmethod
    async def mark_as_incomplete(cls, session: AsyncSession, id: int) -> None:
        """Mark a message as incomplete."""
        stmt = (
            update(Message)
            .where(Message.id == id)
            .values(
                message_status=schemas.MessageStatus.INCOMPLETE,
            )
        )
        await session.execute(stmt)

    @classmethod
    async def create(cls, session: AsyncSession, data: dict) -> "Message":
        """Create a new message."""
        message = cls(**data)
        session.add(message)
        await session.flush()
        return message

    @classmethod
    async def mark_status(
        cls,
        session: AsyncSession,
        id: int,
        status: schemas.MessageStatus,
        completed: datetime | None = None,
    ) -> None:
        """Mark a message as a specific status."""
        stmt = (
            update(Message)
            .where(Message.id == id)
            .values(
                message_status=status,
                completed=completed,
            )
        )
        await session.execute(stmt)


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    run_id = Column(String, unique=True, nullable=True)

    status = Column(SQLEnum(schemas.RunStatus), nullable=False)
    messages = relationship(
        "Message",
        back_populates="run",
    )

    error_code = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    incomplete_reason = Column(String, nullable=True)

    tool_calls = relationship(
        "ToolCall",
        back_populates="run",
    )

    reasoning_steps = relationship(
        "ReasoningStep",
        back_populates="run",
    )

    thread_id = Column(Integer, ForeignKey("threads.id", ondelete="CASCADE"))
    thread = relationship("Thread", back_populates="runs", uselist=False)

    assistant_id = Column(
        Integer, ForeignKey("assistants.id", ondelete="SET NULL"), nullable=True
    )
    model = Column(String, nullable=True)
    reasoning_effort = Column(Integer, nullable=True)
    verbosity = Column(Integer, nullable=True)
    temperature = Column(Float, nullable=True)
    instructions = Column(String, nullable=True)
    tools_available = Column(String, nullable=True)

    creator_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created = Column(DateTime(timezone=True), server_default=func.now())
    updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed = Column(DateTime(timezone=True), nullable=True)

    @classmethod
    async def get_file_search_files_from_messages(
        cls, session: AsyncSession, run_id: int
    ) -> list[str]:
        """Get all file search file ids from messages in a run."""
        stmt = (
            select(File.file_id)
            .select_from(Run)
            .join(Message, Message.run_id == Run.id)
            .join(
                file_search_attachment_association,
                file_search_attachment_association.c.message_id == Message.id,
            )
            .join(File, File.id == file_search_attachment_association.c.file_id)
            .where(Run.id == run_id)
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.fetchall()]

    @classmethod
    async def get_runs_by_thread_id(
        cls, session: AsyncSession, thread_id: int
    ) -> AsyncGenerator["Run", None]:
        """Get all runs associated with a specific thread."""
        stmt = (
            select(Run).where(Run.thread_id == thread_id).order_by(Run.created.desc())
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Run

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id: int) -> "Run":
        """Get a run by its ID."""
        stmt = select(Run).where(Run.id == id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def mark_as_status(
        cls,
        session: AsyncSession,
        id: int,
        status: schemas.RunStatus,
        error_code: str | None,
        error_message: str | None,
        incomplete_reason: str | None,
        completed: bool = True,
    ) -> None:
        stmt = (
            update(Run)
            .where(Run.id == id)
            .values(
                status=status,
                error_code=error_code,
                error_message=error_message,
                incomplete_reason=incomplete_reason,
                completed=func.now() if completed else None,
            )
        )
        await session.execute(stmt)

    @classmethod
    async def update_run_id_status(
        cls,
        session: AsyncSession,
        id_: int,
        run_id: str,
        status: schemas.RunStatus,
    ) -> None:
        """Update the run ID and status for a specific run."""
        stmt = (
            update(Run)
            .where(Run.id == id_)
            .values(
                run_id=run_id,
                status=status,
            )
        )
        await session.execute(stmt)

    @classmethod
    async def update_status(
        cls, session: AsyncSession, id: int, status: schemas.RunStatus
    ) -> None:
        """Update the status for a specific run."""
        stmt = (
            update(Run)
            .where(Run.id == id)
            .values(
                status=status,
            )
        )
        await session.execute(stmt)

    @classmethod
    async def mark_as_pending(
        cls,
        session: AsyncSession,
        id: int,
    ) -> None:
        """Mark a run as pending."""
        stmt = (
            update(Run)
            .where(Run.id == id)
            .values(
                status=schemas.RunStatus.PENDING,
            )
        )
        await session.execute(stmt)


class Thread(Base):
    __tablename__ = "threads"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)
    version = Column(Integer, default=1)
    thread_id = Column(String, unique=True)
    class_id = Column(Integer, ForeignKey("classes.id"))
    class_ = relationship("Class", back_populates="threads")
    assistant_id = Column(Integer, ForeignKey("assistants.id"), index=True)
    assistant = relationship("Assistant", back_populates="threads", uselist=False)
    interaction_mode = Column(
        SQLEnum(schemas.InteractionMode),
        server_default=schemas.InteractionMode.CHAT.name,
    )
    display_user_info = Column(Boolean, server_default="false")
    voice_mode_recording = relationship(
        "VoiceModeRecording",
        back_populates="thread",
        uselist=False,
    )
    instructions = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    private = Column(Boolean)
    user_message_ct = Column(Integer, server_default="1")
    users = relationship(
        "User",
        secondary=user_thread_association,
        back_populates="threads",
    )
    image_files = relationship(
        "File",
        secondary=image_file_thread_association,
        back_populates="threads_images",
    )
    code_interpreter_files = relationship(
        "File",
        secondary=code_interpreter_file_thread_association,
        back_populates="threads",
    )
    code_interpreter_calls = relationship(
        "CodeInterpreterCall",
        back_populates="thread",
    )
    runs = relationship(
        "Run",
        back_populates="thread",
    )
    messages = relationship(
        "Message",
        back_populates="thread",
    )
    tool_calls = relationship(
        "ToolCall",
        back_populates="thread",
    )
    reasoning_steps = relationship(
        "ReasoningStep",
        back_populates="thread",
    )
    tools_available = Column(String)
    vector_store_id = Column(
        Integer,
        ForeignKey("vector_stores.id", name="fk_threads_vector_store_id_vector_store"),
    )
    vector_store = relationship("VectorStore", back_populates="threads", uselist=False)
    anonymous_sessions = relationship(
        "AnonymousSession",
        back_populates="thread",
    )
    conversation_id = Column(String, nullable=True)
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
        stmt_ = delete(user_thread_association).where(
            user_thread_association.c.thread_id == self.id
        )
        stmt = delete(Thread).where(Thread.id == self.id)
        await session.execute(stmt_)
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

        result = await session.execute(
            select(Thread)
            .options(
                joinedload(Thread.users).load_only(
                    User.id,
                    User.created,
                    User.anonymous_link_id,
                    User.first_name,
                    User.last_name,
                    User.display_name,
                    User.email,
                )
            )
            .where(Thread.id == thread.id)
        )
        thread = result.scalars().first()

        return thread

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id_: int) -> "Thread":
        stmt = select(Thread).where(Thread.id == int(id_))
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id_with_ci_file_ids(
        cls, session: AsyncSession, id_: int
    ) -> "Thread":
        stmt = (
            select(Thread)
            .where(Thread.id == int(id_))
            .options(
                selectinload(Thread.code_interpreter_files).load_only(File.file_id)
            )
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id_with_users(cls, session: AsyncSession, id_: int) -> "Thread":
        stmt = (
            select(Thread)
            .where(Thread.id == int(id_))
            .options(
                joinedload(Thread.users).load_only(
                    User.id,
                    User.created,
                    User.anonymous_link_id,
                    User.first_name,
                    User.last_name,
                    User.display_name,
                    User.email,
                )
            )
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id_with_users_voice_mode(
        cls, session: AsyncSession, id_: int
    ) -> "Thread":
        stmt = (
            select(Thread)
            .where(Thread.id == int(id_))
            .options(
                joinedload(Thread.users).load_only(
                    User.id,
                    User.created,
                    User.anonymous_link_id,
                    User.first_name,
                    User.last_name,
                    User.display_name,
                    User.email,
                ),
                selectinload(Thread.voice_mode_recording),
            )
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_by_id_extended_details(
        cls, session: AsyncSession, id_: int
    ) -> "Thread":
        stmt = (
            select(Thread)
            .where(Thread.id == int(id_))
            .options(
                selectinload(Thread.users),
                selectinload(Thread.voice_mode_recording),
                selectinload(Thread.vector_store).selectinload(VectorStore.files),
                selectinload(Thread.code_interpreter_files),
                selectinload(Thread.assistant).options(
                    selectinload(Assistant.vector_store).selectinload(
                        VectorStore.files
                    ),
                    selectinload(Assistant.code_interpreter_files),
                ),
                selectinload(Thread.class_).options(
                    defer(Class.api_key),
                    defer(Class.lms_access_token),
                    defer(Class.lms_refresh_token),
                    selectinload(Class.api_key_obj).options(
                        defer(APIKey.api_key),
                    ),
                ),
                selectinload(Thread.image_files),
                selectinload(Thread.runs).options(
                    selectinload(Run.tool_calls).options(
                        selectinload(ToolCall.outputs),
                        selectinload(ToolCall.results),
                        selectinload(ToolCall.web_search_actions).options(
                            selectinload(WebSearchCallAction.sources),
                        ),
                    ),
                    selectinload(Run.messages).options(
                        selectinload(Message.content).selectinload(
                            MessagePart.annotations
                        ),
                        selectinload(Message.code_interpreter_attachments),
                        selectinload(Message.file_search_attachments),
                    ),
                    selectinload(Run.reasoning_steps).options(
                        selectinload(ReasoningStep.summary_parts),
                        selectinload(ReasoningStep.content_parts),
                    ),
                ),
            )
        )
        return await session.scalar(stmt)

    @classmethod
    async def get_threads_by_assistant_id(
        cls, session: AsyncSession, assistant_id: int, after: datetime | None = None
    ) -> AsyncGenerator["Thread", None]:
        stmt = select(Thread).where(Thread.assistant_id == assistant_id)
        if after:
            stmt = stmt.where(Thread.last_activity > after)
        result = await session.execute(stmt)
        for row in result:
            yield row.Thread

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
    async def get_n(
        cls,
        session: AsyncSession,
        n: int = 10,
        before: datetime | None = None,
        filter_batch: Callable[[list["Thread"]], Coroutine[Any, Any, list["Thread"]]]
        | None = None,
        **kwargs,
    ) -> List["Thread"]:
        if n < 1:
            return []
        threads: List["Thread"] = []
        next_latest_time: datetime | None = before
        while len(threads) < n:
            new_threads = list["Thread"]()
            async for new_thread in cls.get_all(
                session, limit=n, before=next_latest_time, **kwargs
            ):
                if not next_latest_time or new_thread.last_activity < next_latest_time:
                    next_latest_time = new_thread.last_activity
                new_threads.append(new_thread)

            if not new_threads:
                break

            if filter_batch:
                new_threads = await filter_batch(new_threads)

            for new_thread in new_threads:
                threads.append(new_thread)

                if len(threads) >= n:
                    break
        return threads

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
        **kwargs,
    ) -> AsyncGenerator["Thread", None]:
        """Convenience wrapper around `Thread.get_all`.

        See `Thread.get_all` for more information.
        """
        if not ids:
            return

        async for thread in cls.get_all(session, ids=ids, **kwargs):
            yield thread

    @classmethod
    async def get_all(
        cls,
        session: AsyncSession,
        ids: list[int] | None = None,
        limit: int = 10,
        before: datetime | None = None,
        class_id: int | None = None,
        private: bool | None = None,
    ) -> AsyncGenerator["Thread", None]:
        """Get a number of threads optionally filtered by some criteria.

        Might not return exactly the number of threads requested.
        """
        if ids is not None and not ids:
            return

        conditions: list[BinaryExpression[bool]] = []
        if ids:
            conditions.append(Thread.id.in_([int(id_) for id_ in ids]))
        if before:
            conditions.append(Thread.last_activity < before)
        if class_id:
            conditions.append(Thread.class_id == int(class_id))
        if private is not None:
            conditions.append(Thread.private == private)

        condition = and_(True, *conditions)

        stmt = (
            select(Thread)
            .outerjoin(Thread.assistant)
            .options(contains_eager(Thread.assistant).load_only(Assistant.name))
            .options(
                selectinload(Thread.users).load_only(
                    User.id,
                    User.display_name,
                    User.first_name,
                    User.last_name,
                    User.anonymous_link_id,
                    User.created,
                )
            )
            .options(
                selectinload(Thread.anonymous_sessions).load_only(AnonymousSession.id)
            )
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
        include_only_user_ids: list[int] | None = None,
    ) -> AsyncGenerator["Thread", None]:
        condition = Thread.class_id == int(class_id)
        if include_only_user_ids is not None:
            if not include_only_user_ids:
                return
            condition = and_(
                condition, Thread.users.any(User.id.in_(include_only_user_ids))
            )
        stmt = (
            select(Thread)
            .outerjoin(Thread.users)
            .options(
                selectinload(Thread.users).load_only(User.id, User.created),
            )
            .order_by(Thread.updated.desc() if desc else Thread.updated.asc())
            .where(condition)
        )
        result = await session.execute(stmt)
        for row in result:
            yield row.Thread

    @classmethod
    async def add_code_interpreter_files(
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
        cls,
        session: AsyncSession,
        assistant_id: int,
        tools: str,
        version: int,
        interaction_mode: str,
    ) -> None:
        stmt = (
            update(Thread)
            .where(
                and_(
                    Thread.assistant_id == assistant_id,
                    Thread.version == version,
                    Thread.interaction_mode == interaction_mode,
                )
            )
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
    async def get_code_interpreter_file_obj_ids_including_assistant(
        cls, session: AsyncSession, thread_id: int, assistant_id: int
    ) -> list[str]:
        stmt = (
            select(File.file_id)
            .select_from(File)
            .join(
                code_interpreter_file_assistant_association,
                code_interpreter_file_assistant_association.c.file_id == File.id,
                isouter=True,
            )
            .join(
                code_interpreter_file_thread_association,
                code_interpreter_file_thread_association.c.file_id == File.id,
                isouter=True,
            )
            .where(
                or_(
                    code_interpreter_file_thread_association.c.thread_id == thread_id,
                    code_interpreter_file_assistant_association.c.assistant_id
                    == assistant_id,
                )
            )
            .distinct()
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    @classmethod
    async def get_max_output_sequence(
        cls, session: AsyncSession, thread_id: int
    ) -> int:
        combined = union_all(
            select(Message.output_index.label("output_index")).where(
                Message.thread_id == thread_id
            ),
            select(ToolCall.output_index.label("output_index")).where(
                ToolCall.thread_id == thread_id
            ),
        ).subquery()

        stmt = select(func.coalesce(func.max(combined.c.output_index), -1))

        result = await session.execute(stmt)
        return result.scalar_one()

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

    @classmethod
    async def get_by_id_with_assistant(
        cls, session: AsyncSession, thread_id: int
    ) -> "Thread":
        """Get a thread by its thread_id with the assistant eager loaded."""
        stmt = (
            select(Thread)
            .options(joinedload(Thread.assistant))
            .where(Thread.id == thread_id)
        )
        result = await session.execute(stmt)
        thread = result.scalar()
        return thread

    @classmethod
    async def list_messages(
        cls,
        session: AsyncSession,
        thread_id: int,
        limit: int = 100,
        before: int | None = None,
        after: int | None = None,
        order: Literal["asc", "desc"] = "desc",
    ) -> list["Message"]:
        stmt = select(Message).where(Message.thread_id == thread_id)

        if before is not None:
            stmt = stmt.where(Message.id < before)
        if after is not None:
            stmt = stmt.where(Message.id > after)

        ordering = (
            asc(Message.output_index) if order == "asc" else desc(Message.output_index)
        )
        stmt = (
            stmt.order_by(ordering).limit(limit).options(selectinload(Message.content))
        )

        result = await session.execute(stmt)
        return result.scalars().all()

    @classmethod
    async def list_all_messages_gen(
        cls,
        session: AsyncSession,
        thread_id: int,
    ) -> AsyncGenerator["Message", None]:
        stmt = (
            select(Message)
            .where(Message.thread_id == thread_id)
            .options(
                selectinload(Message.content).selectinload(MessagePart.annotations),
                selectinload(Message.file_search_attachments),
                selectinload(Message.code_interpreter_attachments),
            )
        )
        result = await session.execute(stmt)
        for message in result.scalars().all():
            yield message

    @classmethod
    async def list_all_tool_calls_gen(
        cls,
        session: AsyncSession,
        thread_id: int,
    ) -> AsyncGenerator["ToolCall", None]:
        stmt = (
            select(ToolCall)
            .where(ToolCall.thread_id == thread_id)
            .options(
                selectinload(ToolCall.results),
                selectinload(ToolCall.outputs),
                selectinload(ToolCall.web_search_actions).selectinload(
                    WebSearchCallAction.sources
                ),
            )
        )
        result = await session.execute(stmt)
        for tool_call in result.scalars().all():
            yield tool_call

    @classmethod
    async def list_all_reasoning_steps_gen(
        cls,
        session: AsyncSession,
        thread_id: int,
    ) -> AsyncGenerator["ReasoningStep", None]:
        stmt = (
            select(ReasoningStep)
            .where(ReasoningStep.thread_id == thread_id)
            .options(
                selectinload(ReasoningStep.content_parts),
                selectinload(ReasoningStep.summary_parts),
            )
        )
        result = await session.execute(stmt)
        for reasoning_step in result.scalars().all():
            yield reasoning_step

    @classmethod
    async def list_messages_tool_calls(
        cls,
        session: AsyncSession,
        thread_id: int,
        limit: int = 100,
        before: str | None = None,
        after: str | None = None,
        order: Literal["asc", "desc"] = "desc",
    ) -> tuple[list["Message"], list["ToolCall"]]:
        msg_stmt = select(
            Message.id.label("id"),
            Message.output_index.label("output_index"),
            literal_column("'message'").label("type"),
        ).where(Message.thread_id == thread_id)
        if before is not None:
            msg_stmt = msg_stmt.where(Message.id < int(before))
        if after is not None:
            msg_stmt = msg_stmt.where(Message.id > int(after))

        tool_stmt = select(
            ToolCall.id.label("id"),
            ToolCall.output_index.label("output_index"),
            literal_column("'tool_call'").label("type"),
        ).where(ToolCall.thread_id == thread_id)
        if before is not None:
            tool_stmt = tool_stmt.where(ToolCall.id < int(before))
        if after is not None:
            tool_stmt = tool_stmt.where(ToolCall.id > int(after))

        combined_stmt = union_all(msg_stmt, tool_stmt)
        ordering = asc("output_index") if order == "asc" else desc("output_index")
        stmt = (
            select(combined_stmt.c.id, combined_stmt.c.type)
            .order_by(ordering)
            .limit(limit)
        )

        result = await session.execute(stmt)
        rows = result.all()

        messages_ids = [r.id for r in rows if r.type == "message"]
        tool_call_ids = [r.id for r in rows if r.type == "tool_call"]

        messages = await session.execute(
            select(Message)
            .where(Message.id.in_(messages_ids))
            .order_by(ordering)
            .options(
                selectinload(Message.content).selectinload(MessagePart.annotations),
                selectinload(Message.file_search_attachments),
                selectinload(Message.code_interpreter_attachments),
            )
        )
        tool_calls = await session.execute(
            select(ToolCall)
            .where(ToolCall.id.in_(tool_call_ids))
            .order_by(ordering)
            .options(
                selectinload(ToolCall.results),
                selectinload(ToolCall.outputs),
                selectinload(ToolCall.web_search_actions).selectinload(
                    WebSearchCallAction.sources
                ),
            )
        )

        return messages.scalars().all(), tool_calls.scalars().all()

    @classmethod
    async def get_all_threads_by_version(
        cls, session: AsyncSession, version: int
    ) -> AsyncGenerator["Thread", None]:
        """Get all threads by version."""
        stmt = select(Thread).where(Thread.version == version)
        result = await session.execute(stmt)
        for thread in result:
            yield thread.Thread

    @classmethod
    async def get_latest_run_by_thread_id(
        cls, session: AsyncSession, thread_id: int
    ) -> "Run":
        """Get the latest run for a specific thread."""
        stmt = (
            select(Run)
            .where(Run.thread_id == thread_id)
            .order_by(Run.created.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
