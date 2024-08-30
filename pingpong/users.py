from abc import ABC, abstractmethod
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

        for ucr in self.new_ucr.roles:
            await self._check_permissions(ucr)
            user = await models.User.get_or_create_by_email(self.session, ucr.email)

            if self.new_ucr.lms_tenant:
                self.newly_synced.append(user.id)
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

            if enrollment.lms_tenant and not self.new_ucr.lms_tenant:
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
