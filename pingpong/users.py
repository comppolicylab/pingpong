from abc import ABC, abstractmethod
import asyncio
from pingpong.authz.openfga import OpenFgaAuthzClient
import pingpong.models as models
import pingpong.schemas as schemas

from fastapi import BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from .auth import generate_auth_link
from .authz import Relation
from .config import config
from .invite import send_invite
from .now import NowFn, utcnow
from sqlalchemy import literal, select, delete, update
from sqlalchemy.orm import aliased
from .models import User, UserClassRole, UserInstitutionRole


class AddUserException(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


async def delete_canvas_permissions(
    client: OpenFgaAuthzClient, user_ids: list[int], class_id: str
) -> None:
    revokes = list[Relation]()
    revokes = [
        (f"user:{user_id}", role, f"class:{class_id}")
        for user_id in user_ids
        for role in ["admin", "teacher", "student"]
    ]
    await client.write_safe(revoke=revokes)


class CheckUserPermissionException(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


async def check_permissions(request: Request, uid: int, cid: int):
    # CHECK 1: Is the requesting user trying to edit themselves?
    if uid == request.state.session.user.id:
        raise CheckUserPermissionException(
            code=403, detail="You cannot manage your own user role."
        )

    # CHECK 2: Does requesting user have enough permissions to edit this type of user?
    # Query to find the current permissions for the requester and the user being modified.
    me_ent = f"user:{request.state.session.user.id}"
    them_ent = f"user:{uid}"
    class_obj = f"class:{cid}"
    perms = await request.state.authz.check(
        [
            (me_ent, "admin", class_obj),
            (me_ent, "teacher", class_obj),
            (me_ent, "student", class_obj),
            (them_ent, "admin", class_obj),
            (them_ent, "teacher", class_obj),
            (them_ent, "student", class_obj),
        ]
    )
    ordered_roles = ["admin", "teacher", "student", None]
    my_perms = [r for r, p in zip(ordered_roles[:3], perms[:3]) if p]
    their_perms = [r for r, p in zip(ordered_roles[:3], perms[3:]) if p]

    # Figure out the role with maximal permissions for each user.
    # (This is necessary because users might have multiple roles. This
    # is especially true with inherited `admin` permissions.)
    my_primary_role = next(
        (r for r in ordered_roles if r in my_perms),
        None,
    )
    their_primary_role = next(
        (r for r in ordered_roles if r in their_perms),
        None,
    )

    my_primary_idx = ordered_roles.index(my_primary_role)
    their_primary_idx = ordered_roles.index(their_primary_role)

    # If they already have more permissions than we do, we can't remove them them
    if their_primary_idx < my_primary_idx:
        raise CheckUserPermissionException(
            code=403, detail="Lacking permission to manage this user."
        )

    existing = await models.UserClassRole.get(request.state.db, uid, cid)

    # CHECK 3: Is the user being edited a member of this group?
    if not existing:
        raise CheckUserPermissionException(code=404, detail="User not found in group.")

    # CHECK 4: Is the user imported from an LMS?
    if existing.lms_tenant:
        raise CheckUserPermissionException(
            code=403,
            detail="You cannot manually edit an imported user. Please update or remove the user through your Canvas roster.",
        )


class MergeUsers:
    def __init__(
        self,
        session: AsyncSession,
        client: OpenFgaAuthzClient,
        new_user_id: int,
        old_user_id: int,
    ) -> None:
        self.session = session
        self.client = client
        self.nid = new_user_id
        self.oid = old_user_id

    async def merge(self) -> "User":
        await asyncio.gather(
            self.merge_classes(),
            self.merge_institutions(),
            self.merge_assistants(),
            self.merge_threads(),
            self.merge_lms_users(),
            self.merge_external_logins(),
            self.merge_user_files(),
            self.merge_permissions(),
        )
        return await self.merge_users()

    async def merge_classes(self) -> None:
        # Step 1: Find classes the old user is enrolled in and the new user is not
        old_user_classes = aliased(UserClassRole)
        new_user_classes = aliased(UserClassRole)

        # Step 2: Subquery to find classes where oid is enrolled but nid is not
        subquery = (
            select(
                old_user_classes.class_id,
                old_user_classes.role,
                old_user_classes.title,
                old_user_classes.lms_tenant,
                old_user_classes.lms_type,
                literal(self.nid).label(
                    "user_id"
                ),  # Include nid directly as the new user_id
            )
            .outerjoin(
                new_user_classes,
                (new_user_classes.class_id == old_user_classes.class_id)
                & (new_user_classes.user_id == self.nid),
            )
            .where(
                old_user_classes.user_id == self.oid, new_user_classes.user_id.is_(None)
            )
        )

        # Step 3: Use _get_upsert_stmt to upsert records
        upsert_stmt = (
            models._get_upsert_stmt(self.session)(UserClassRole)
            .from_select(
                [
                    UserClassRole.class_id,
                    UserClassRole.role,
                    UserClassRole.title,
                    UserClassRole.lms_tenant,
                    UserClassRole.lms_type,
                    UserClassRole.user_id,
                ],
                subquery,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    UserClassRole.user_id,
                    UserClassRole.class_id,
                ]
            )
        )
        await self.session.execute(upsert_stmt)

        # Step 4: Remove the old user from all classes
        delete_stmt = delete(UserClassRole).where(UserClassRole.user_id == self.oid)
        await self.session.execute(delete_stmt)

    async def merge_institutions(self) -> None:
        # Alias for old and new user institutions
        old_user_institutions = aliased(UserInstitutionRole)
        new_user_institutions = aliased(UserInstitutionRole)

        # Subquery to find institutions where old user is associated but new user is not
        subquery = (
            select(
                old_user_institutions.institution_id,
                old_user_institutions.role,
                old_user_institutions.title,
                literal(self.nid).label(
                    "user_id"
                ),  # Include nid directly as the new user_id
            )
            .outerjoin(
                new_user_institutions,
                (
                    new_user_institutions.institution_id
                    == old_user_institutions.institution_id
                )
                & (new_user_institutions.user_id == self.nid),
            )
            .where(
                old_user_institutions.user_id == self.oid,
                new_user_institutions.user_id.is_(None),
            )
        )

        # Use _get_upsert_stmt to upsert records
        upsert_stmt = (
            models._get_upsert_stmt(self.session)(UserInstitutionRole)
            .from_select(
                [
                    UserInstitutionRole.institution_id,
                    UserInstitutionRole.role,
                    UserInstitutionRole.title,
                    UserInstitutionRole.user_id,
                ],
                subquery,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    UserInstitutionRole.user_id,
                    UserInstitutionRole.institution_id,
                ]
            )
        )
        await self.session.execute(upsert_stmt)

        # Remove the old user from all institutions
        delete_stmt = delete(UserInstitutionRole).where(
            UserInstitutionRole.user_id == self.oid
        )
        await self.session.execute(delete_stmt)

    async def merge_assistants(self) -> None:
        stmt = (
            update(models.Assistant)
            .where(models.Assistant.creator_id == self.oid)
            .values(creator_id=self.nid)
        )
        await self.session.execute(stmt)

    async def merge_threads(self) -> None:
        stmt = (
            update(models.user_thread_association)
            .where(models.user_thread_association.c.user_id == self.oid)
            .values(user_id=self.nid)
        )
        await self.session.execute(stmt)

    async def merge_lms_users(self) -> None:
        stmt = (
            update(models.Class)
            .where(models.Class.lms_user_id == self.oid)
            .values(lms_user_id=self.nid)
        )
        await self.session.execute(stmt)

    async def merge_external_logins(self) -> None:
        # Step 1: Aliased references to ExternalLogin model
        old_user_logins = aliased(models.ExternalLogin)
        new_user_logins = aliased(models.ExternalLogin)

        # Step 2: Subquery to find logins where oid is present, but nid is not
        subquery = (
            select(
                old_user_logins.provider,
                old_user_logins.identifier,
                literal(self.nid).label("user_id"),  # Use nid as the new user_id
            )
            .outerjoin(
                new_user_logins,
                (new_user_logins.provider == old_user_logins.provider)
                & (new_user_logins.user_id == self.nid),
            )
            .where(
                old_user_logins.user_id == self.oid, new_user_logins.user_id.is_(None)
            )
        )

        # Step 3: Use _get_upsert_stmt to upsert records
        upsert_stmt = (
            models._get_upsert_stmt(self.session)(models.ExternalLogin)
            .from_select(
                [
                    models.ExternalLogin.provider,
                    models.ExternalLogin.identifier,
                    models.ExternalLogin.user_id,
                ],
                subquery,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    models.ExternalLogin.user_id,
                    models.ExternalLogin.provider,
                ]
            )
        )
        await self.session.execute(upsert_stmt)

        # Step 4: Remove the old user logins
        delete_stmt = delete(models.ExternalLogin).where(
            models.ExternalLogin.user_id == self.oid
        )
        await self.session.execute(delete_stmt)

    async def merge_user_files(self) -> None:
        stmt = (
            update(models.File)
            .where(models.File.uploader_id == self.oid)
            .values(uploader_id=self.nid)
        )
        await self.session.execute(stmt)

    async def merge_permissions(self) -> None:
        old_root_admin = await self.client.list(
            f"user:{self.oid}",
            "admin",
            "root",
        )
        compos_old_root_can_create_institution = await self.client.list(
            f"user:{self.oid}",
            "can_create_institution",
            "root",
        )
        old_root_can_create_institution = list(
            set(compos_old_root_can_create_institution) - set(old_root_admin)
        )
        old_root_can_do_reckless_things = await self.client.list(
            f"user:{self.oid}",
            "can_do_reckless_things",
            "root",
        )
        old_institution_admin = await self.client.list(
            f"user:{self.oid}",
            "admin",
            "institution",
        )
        compos_old_institution_can_create_class = await self.client.list(
            f"user:{self.oid}",
            "can_create_class",
            "institution",
        )
        old_institution_can_create_class = list(
            set(compos_old_institution_can_create_class) - set(old_institution_admin)
        )
        compos_old_class_admin = await self.client.list(
            f"user:{self.oid}",
            "admin",
            "class",
        )
        old_class_admin = list(set(compos_old_class_admin) - set(old_institution_admin))
        old_class_teacher = await self.client.list(
            f"user:{self.oid}",
            "teacher",
            "class",
        )
        old_class_student = await self.client.list(
            f"user:{self.oid}",
            "student",
            "class",
        )
        old_threads_party = await self.client.list(
            f"user:{self.oid}",
            "party",
            "thread",
        )
        old_assistant_owner = await self.client.list(
            f"user:{self.oid}",
            "owner",
            "assistant",
        )
        old_user_file_owner = await self.client.list(
            f"user:{self.oid}",
            "owner",
            "user_file",
        )
        old_class_file_owner = await self.client.list(
            f"user:{self.oid}",
            "owner",
            "class_file",
        )
        grants = list[Relation]()
        revokes = list[Relation]()
        for perm in old_root_admin:
            revokes.append((f"user:{self.oid}", "admin", f"root:{perm}"))
            grants.append((f"user:{self.nid}", "admin", f"root:{perm}"))
        for perm in old_root_can_create_institution:
            revokes.append(
                (f"user:{self.oid}", "can_create_institution", f"root:{perm}")
            )
            grants.append(
                (f"user:{self.nid}", "can_create_institution", f"root:{perm}")
            )
        for perm in old_root_can_do_reckless_things:
            revokes.append(
                (f"user:{self.oid}", "can_do_reckless_things", f"root:{perm}")
            )
            grants.append(
                (f"user:{self.nid}", "can_do_reckless_things", f"root:{perm}")
            )
        for perm in old_institution_admin:
            revokes.append((f"user:{self.oid}", "admin", f"institution:{perm}"))
            grants.append((f"user:{self.nid}", "admin", f"institution:{perm}"))
        for perm in old_institution_can_create_class:
            revokes.append(
                (f"user:{self.oid}", "can_create_class", f"institution:{perm}")
            )
            grants.append(
                (f"user:{self.nid}", "can_create_class", f"institution:{perm}")
            )
        for perm in old_class_admin:
            revokes.append((f"user:{self.oid}", "admin", f"class:{perm}"))
            grants.append((f"user:{self.nid}", "admin", f"class:{perm}"))
        for perm in old_class_teacher:
            revokes.append((f"user:{self.oid}", "teacher", f"class:{perm}"))
            grants.append((f"user:{self.nid}", "teacher", f"class:{perm}"))
        for perm in old_class_student:
            revokes.append((f"user:{self.oid}", "student", f"class:{perm}"))
            grants.append((f"user:{self.nid}", "student", f"class:{perm}"))
        for perm in old_threads_party:
            revokes.append((f"user:{self.oid}", "party", f"thread:{perm}"))
            grants.append((f"user:{self.nid}", "party", f"thread:{perm}"))
        for perm in old_assistant_owner:
            revokes.append((f"user:{self.oid}", "owner", f"assistant:{perm}"))
            grants.append((f"user:{self.nid}", "owner", f"assistant:{perm}"))
        for perm in old_user_file_owner:
            revokes.append((f"user:{self.oid}", "owner", f"user_file:{perm}"))
            grants.append((f"user:{self.nid}", "owner", f"user_file:{perm}"))
        for perm in old_class_file_owner:
            revokes.append((f"user:{self.oid}", "owner", f"class_file:{perm}"))
            grants.append((f"user:{self.nid}", "owner", f"class_file:{perm}"))
        await self.client.write_safe(grant=grants, revoke=revokes)

    async def merge_users(self) -> "User":
        old_user = await models.User.get_by_id(self.session, self.oid)
        new_user = await models.User.get_by_id(self.session, self.nid)

        match old_user.state:
            case "verified":
                new_user.state = (
                    "verified" if new_user.state != "banned" else new_user.state
                )
            case "banned":
                new_user.state = "banned"
            case _:
                pass

        new_user.super_admin = new_user.super_admin or old_user.super_admin
        stmt = delete(models.User).where(models.User.id == self.oid)
        await self.session.execute(stmt)
        self.session.add(new_user)
        await self.session.flush()
        await self.session.refresh(new_user)
        return new_user


class AddNewUsers(ABC):
    def __init__(
        self,
        class_id: str,
        new_ucr: schemas.CreateUserClassRoles,
        user_id: int,
        session: AsyncSession,
        client: OpenFgaAuthzClient,
    ):
        self.class_id = int(class_id)
        self.new_ucr = new_ucr
        self.user_id = user_id
        self.session = session
        self.client = client

    @abstractmethod
    def send_invites(self):
        pass

    async def _merge_accounts(self):
        for user_id, sso_id in self.newly_synced_identifiers.items():
            user_ids = await models.ExternalLogin.accounts_to_merge(
                self.session,
                user_id,
                provider=self.new_ucr.sso_tenant,
                identifier=sso_id,
            )

            # Merge accounts
            for uid in user_ids:
                await MergeUsers(self.session, self.client, user_id, uid).merge()

    def _permissions_to_revoke(self, user_ids: list[int]) -> list[Relation]:
        """Generate permissions to revoke after deleting enrollment for a list of users."""

        return [
            (f"user:{user_id}", role, f"class:{str(self.class_id)}")
            for user_id in user_ids
            for role in ["admin", "teacher", "student"]
        ]

    async def _init_invites(self) -> schemas.CreateUserInviteConfig:
        invite_config = schemas.CreateUserInviteConfig()

        # Roles to display in the email invite
        invite_config.formatted_roles = {
            "admin": "an Administrator",
            "teacher": "a Moderator",
            "student": "a Member",
        }

        # Get the display name of the user who initiated the request to display in the email invite
        invite_config.inviter_display_name = await models.User.get_display_name(
            self.session,
            self.user_id,
        )

        return invite_config

    async def _check_permissions(self, ucr: schemas.UserClassRole):
        if not self.is_admin and ucr.roles.admin:
            raise AddUserException(
                code=403, detail="Lacking permission to add Administrators."
            )

        if not self.is_supervisor and ucr.roles.teacher:
            raise AddUserException(
                code=403, detail="Lacking permission to add Moderators."
            )

    async def _update_user_enrollment(
        self,
        enrollment: schemas.UserClassRole,
        roles: schemas.ClassUserRoles,
        sso_id: str | None = None,
    ):
        self.new_roles.append(
            schemas.UserClassRole(
                user_id=enrollment.user_id,
                class_id=enrollment.class_id,
                roles=roles,
            )
        )

        # Update the LMS tenant if it's provided
        # There might be cases where the user is already enrolled in the class
        # through a manual invite, and we want to make sure the LMS tenant is updated.
        #
        # DESIGN DECISION: LMS sync always takes precedence over manual invites.
        # For example, a user that was manually invited but then synced through LMS
        # will be deleted if they are no longer on the LMS roster.
        # TODO: This might not be the desired behavior in all cases. Add a UI option to
        # control this behavior.
        if self.new_ucr.lms_tenant:
            enrollment.lms_tenant = self.new_ucr.lms_tenant
            enrollment.lms_type = self.new_ucr.lms_type
            enrollment.sso_id = sso_id
            enrollment.sso_tenant = self.new_ucr.sso_tenant
            self.session.add(enrollment)

    async def _create_user_enrollment(
        self,
        user: models.User,
        ucr: schemas.UserClassRole,
        invite_roles: list[str] = [],
        sso_id: str | None = None,
    ):
        # Create the user enrollment
        enrollment = await models.UserClassRole.create(
            self.session,
            user.id,
            self.class_id,
            self.new_ucr.lms_tenant,
            self.new_ucr.lms_type,
            self.new_ucr.sso_tenant,
            sso_id,
        )

        self.new_roles.append(
            schemas.UserClassRole(
                user_id=enrollment.user_id,
                class_id=enrollment.class_id,
                roles=ucr.roles,
            )
        )

        if not self.new_ucr.silent:
            self.invite_config.invites.append(
                schemas.CreateInvite(
                    user_id=user.id,
                    email=user.email,
                    class_name=self.class_.name,
                    inviter_name=self.invite_config.inviter_display_name,
                    formatted_role=", ".join(invite_roles) if invite_roles else None,
                )
            )

    async def _remove_deleted_users(self):
        # Find users that were previously synced but are no longer on the roster
        # and delete their class enrollments
        users_to_delete = await models.UserClassRole.delete_from_sync_list(
            self.session,
            self.class_id,
            self.newly_synced,
            self.new_ucr.lms_tenant,
            self.new_ucr.lms_type,
        )
        # Finally, add permission revokes for the users that were deleted
        self.revokes.extend(self._permissions_to_revoke(users_to_delete))

    async def add_new_users(self) -> schemas.UserClassRoles:
        """
        Add new users to a class.
        """

        self.class_ = await models.Class.get_by_id(self.session, self.class_id)
        self.new_roles: list[schemas.UserClassRole] = []

        grants = list[Relation]()
        self.revokes = list[Relation]()

        self.is_admin = await self.client.test(
            f"user:{self.user_id}", "admin", f"class:{self.class_id}"
        )

        self.is_supervisor = await self.client.test(
            f"user:{self.user_id}", "supervisor", f"class:{self.class_id}"
        )

        if not self.new_ucr.silent:
            self.invite_config = await self._init_invites()

        # If the request is from LMS, we need to store the newly synced users
        # so we can delete previously synced users that are no longer on the roster
        if self.new_ucr.lms_tenant:
            self.newly_synced: list[int] = []
            self.newly_synced_identifiers: dict[int, str | None] = {}

        for ucr in self.new_ucr.roles:
            await self._check_permissions(ucr)
            user = await models.User.get_or_create_by_email(self.session, ucr.email)

            if self.new_ucr.lms_tenant:
                self.newly_synced.append(user.id)
                self.newly_synced_identifiers[user.id] = ucr.sso_id
            if user.id == self.user_id:
                # We don't want an LMS sync to change the roles of the user who initiated it
                if self.new_ucr.lms_tenant:
                    continue
                # If the user is an admin, they can't demote themselves
                else:
                    raise AddUserException(
                        code=403, detail="You cannot change your own role."
                    )

            # Check if the user is already enrolled in the class
            enrollment = await models.UserClassRole.get(
                self.session, user.id, self.class_id
            )

            if enrollment and enrollment.lms_tenant and not self.new_ucr.lms_tenant:
                raise AddUserException(
                    code=403,
                    detail="You cannot manually change the role of an imported user. Please update the user's role in Canvas.",
                )

            invite_roles = []
            for role in ["admin", "teacher", "student"]:
                if getattr(ucr.roles, role):
                    grants.append((f"user:{user.id}", role, f"class:{self.class_id}"))
                    if not self.new_ucr.silent:
                        invite_roles.append(self.invite_config.formatted_roles[role])
                else:
                    self.revokes.append(
                        (f"user:{user.id}", role, f"class:{self.class_id}")
                    )

            if enrollment:
                await self._update_user_enrollment(enrollment, ucr.roles, ucr.sso_id)
            else:
                await self._create_user_enrollment(user, ucr, invite_roles, ucr.sso_id)

        # Send emails to new users in the background
        if not self.new_ucr.silent:
            self.send_invites()

        if self.new_ucr.lms_tenant:
            await self._remove_deleted_users()
            await self._merge_accounts()

        await self.client.write_safe(grant=grants, revoke=self.revokes)
        return schemas.UserClassRoles(roles=self.new_roles)


class AddNewUsersManual(AddNewUsers):
    def __init__(
        self,
        class_id: str,
        new_ucr: schemas.CreateUserClassRoles,
        request: Request,
        tasks: BackgroundTasks,
    ):
        super().__init__(
            class_id,
            new_ucr,
            request.state.session.user.id,
            request.state.db,
            request.state.authz,
        )
        self.request = request
        self.tasks = tasks

    def get_now_fn(self) -> NowFn:
        """Get the current time function for the request."""
        return getattr(self.request.app.state, "now", utcnow)

    def send_invites(self):
        nowfn = self.get_now_fn()
        for invite in self.invite_config.invites:
            magic_link = generate_auth_link(
                invite.user_id, expiry=86_400 * 7, nowfn=nowfn
            )
            self.tasks.add_task(
                send_invite,
                config.email.sender,
                invite,
                magic_link,
                86_400 * 7,
            )


class AddNewUsersScript(AddNewUsers):
    def __init__(
        self,
        class_id: str,
        user_id: int,
        session: AsyncSession,
        client: OpenFgaAuthzClient,
        new_ucr: schemas.CreateUserClassRoles,
    ):
        super().__init__(class_id, new_ucr, user_id, session, client)

    def get_now_fn(self) -> NowFn:
        """Get the current time function for the request."""
        return utcnow

    def send_invites(self):
        nowfn = self.get_now_fn()
        for invite in self.invite_config.invites:
            magic_link = generate_auth_link(
                invite.user_id, expiry=86_400 * 7, nowfn=nowfn
            )
            send_invite(
                config.email.sender,
                invite,
                magic_link,
                86_400 * 7,
            )
