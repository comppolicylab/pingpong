from abc import ABC, abstractmethod
import logging
from typing import Optional
from pingpong.authz.openfga import OpenFgaAuthzClient
from email_validator import validate_email, EmailSyntaxError
import pingpong.models as models
import pingpong.schemas as schemas

from fastapi import BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from .auth import generate_auth_link
from .authz import Relation
from .config import config
from .invite import send_invite
from .now import NowFn, utcnow
from .merge import merge

logger = logging.getLogger(__name__)


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
        if not self.new_ucr.sso_tenant:
            return
        for user_id, sso_id in self.newly_synced_identifiers.items():
            if not sso_id:
                continue
            user_ids = await models.ExternalLogin.accounts_to_merge(
                self.session,
                user_id,
                provider=self.new_ucr.sso_tenant,
                identifier=sso_id,
            )

            # Merge accounts
            for uid in user_ids:
                await merge(self.session, self.client, user_id, uid)

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

    async def _check_permissions(self, ucr: schemas.UserClassRole) -> Optional[str]:
        if not self.is_admin and ucr.roles.admin:
            logger.info("add_users_to_class: AddUserException occurred")
            return "Lacking permission to add Administrators."

        if not self.is_supervisor and ucr.roles.teacher:
            logger.info("add_users_to_class: AddUserException occurred")
            return "Lacking permission to add Moderators."

        return None

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
            self.session.add(enrollment)

        # Update the external login identifier if it's provided
        if sso_id and self.new_ucr.sso_tenant:
            await models.ExternalLogin.create_or_update(
                self.session,
                enrollment.user_id,
                self.new_ucr.sso_tenant,
                sso_id,
            )

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

    async def add_new_users(self) -> schemas.CreateUserResults:
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

        results: list[schemas.CreateUserResult] = []
        for ucr in self.new_ucr.roles:
            error = await self._check_permissions(ucr)
            if error:
                logger.info("add_users_to_class: AddUserException occurred")
                results.append(
                    schemas.CreateUserResult(
                        email=ucr.email, display_name=ucr.display_name, error=error
                    )
                )
                continue
            try:
                ucr.email = validate_email(
                    ucr.email, check_deliverability=False
                ).normalized
            except EmailSyntaxError as e:
                logger.info("add_users_to_class: AddUserException occurred")
                results.append(
                    schemas.CreateUserResult(
                        email=ucr.email,
                        display_name=ucr.display_name,
                        error=str(e),
                    )
                )
                continue
            user = await models.User.get_or_create_by_email_sso(
                self.session,
                ucr.email,
                self.new_ucr.sso_tenant,
                ucr.sso_id,
                display_name=ucr.display_name,
            )

            display_name = (
                user.first_name + " " + user.last_name
                if user.first_name and user.last_name
                else user.display_name
                if user.display_name
                else None
            )

            if self.new_ucr.lms_tenant:
                self.newly_synced.append(user.id)
                self.newly_synced_identifiers[user.id] = ucr.sso_id
            if user.id == self.user_id:
                # We don't want an LMS sync to change the roles of the user who initiated it
                if self.new_ucr.lms_tenant:
                    continue
                # If the user is an admin, they can't demote themselves
                else:
                    logger.info("add_users_to_class: AddUserException occurred")
                    results.append(
                        schemas.CreateUserResult(
                            email=ucr.email,
                            display_name=display_name,
                            error="You cannot change your own role.",
                        )
                    )
                    continue

            # Check if the user is already enrolled in the class
            enrollment = await models.UserClassRole.get(
                self.session, user.id, self.class_id
            )

            if enrollment and enrollment.lms_tenant and not self.new_ucr.lms_tenant:
                logger.info("add_users_to_class: AddUserException occurred")
                results.append(
                    schemas.CreateUserResult(
                        email=ucr.email,
                        display_name=display_name,
                        error="You cannot manually change the role of an imported user. Please update the user's role in Canvas.",
                    )
                )
                continue

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
                results.append(
                    schemas.CreateUserResult(email=ucr.email, display_name=display_name)
                )
            else:
                await self._create_user_enrollment(user, ucr, invite_roles, ucr.sso_id)
                results.append(
                    schemas.CreateUserResult(email=ucr.email, display_name=display_name)
                )

        # Send emails to new users in the background
        if not self.new_ucr.silent:
            self.send_invites()

        if self.new_ucr.lms_tenant:
            await self._remove_deleted_users()
            await self._merge_accounts()

        await self.client.write_safe(grant=grants, revoke=self.revokes)
        return schemas.CreateUserResults(results=results)


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
                invite.user_id,
                expiry=86_400 * 7,
                nowfn=nowfn,
                redirect=f"group/{self.class_id}",
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
                invite.user_id,
                expiry=86_400 * 7,
                nowfn=nowfn,
                redirect=f"group/{self.class_id}",
            )
            send_invite(
                config.email.sender,
                invite,
                magic_link,
                86_400 * 7,
            )
