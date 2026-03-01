from abc import ABC, abstractmethod
import logging
from typing import Optional, cast
from pingpong.authz.openfga import OpenFgaAuthzClient
from email_validator import validate_email, EmailSyntaxError
from pingpong.bg_tasks import safe_task
import pingpong.models as models
import pingpong.schemas as schemas

from fastapi import BackgroundTasks
from pingpong.state_types import AppState, StateRequest
from sqlalchemy.ext.asyncio import AsyncSession
from .auth import generate_auth_link
from .authz import Relation
from .config import config
from .invite import send_invite
from .now import NowFn, utcnow
from .merge import merge

logger = logging.getLogger(__name__)


class UserNotFoundException(Exception):
    def __init__(self, detail: str = "", user_id: str = ""):
        self.user_id = user_id
        self.detail = detail


class AddUserException(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


async def delete_canvas_permissions(
    client: OpenFgaAuthzClient, user_ids: list[int], class_id: str
) -> None:
    revokes: list[Relation] = [
        (f"user:{user_id}", role, f"class:{class_id}")
        for user_id in user_ids
        for role in ["admin", "teacher", "student"]
    ]
    await client.write_safe(revoke=revokes)


class CheckUserPermissionException(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


async def check_permissions(request: StateRequest, uid: int, cid: int):
    supervisor_permission_ids = await request.state["authz"].list_entities(
        f"class:{cid}",
        "supervisor",
        "user",
    )
    supervisors = await models.User.get_all_by_id_if_in_class(
        request.state["db"], supervisor_permission_ids, cid
    )
    supervisor_ids = [s.id for s in supervisors]

    # CHECK 1: Is the requesting user trying to edit themselves?
    # Check that the user is an admin.
    # Check that there is at least one more moderator in the group
    if uid == request.state["session"].user.id:
        if not await request.state["authz"].test(
            f"user:{uid}", "admin", f"class:{cid}"
        ):
            raise CheckUserPermissionException(
                code=403, detail="You cannot change your role in the Group."
            )

        if len(supervisor_ids) < 2 and uid in supervisor_ids:
            raise CheckUserPermissionException(
                code=403,
                detail="You cannot change your role when you're the only Moderator in the Group.",
            )

    # CHECK 2: Are we trying to edit the only supervisor in the group?
    # Check that there is at least one more moderator in the group
    if uid in supervisor_ids:
        if len(supervisor_ids) < 2:
            raise CheckUserPermissionException(
                code=403, detail="You cannot remove the only Moderator in the Group."
            )

    # CHECK 3: Does requesting user have enough permissions to edit this type of user?
    # Query to find the current permissions for the requester and the user being modified.
    me_ent = f"user:{request.state['session'].user.id}"
    them_ent = f"user:{uid}"
    class_obj = f"class:{cid}"
    perms = await request.state["authz"].check(
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

    existing = await models.UserClassRole.get(request.state["db"], uid, cid)

    # CHECK 4: Is the user being edited a member of this group?
    if not existing:
        raise CheckUserPermissionException(code=404, detail="User not found in group.")

    # CHECK 5: Is the user imported from an LMS?
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
        self._external_login_provider_name_cache: dict[int, str | None] = {}

    @abstractmethod
    def send_invites(self):
        pass

    def _get_legacy_external_login_lookup_item(
        self, ucr: schemas.CreateUserClassRole
    ) -> schemas.ExternalLoginLookupItem | None:
        if not self.new_ucr.sso_tenant or not ucr.sso_id:
            return None

        return schemas.ExternalLoginLookupItem(
            provider=self.new_ucr.sso_tenant,
            identifier=ucr.sso_id,
        )

    def _get_identity_lookup_items(
        self, ucr: schemas.CreateUserClassRole
    ) -> list[schemas.ExternalLoginLookupItem]:
        if ucr.external_logins:
            return list(ucr.external_logins)

        legacy_item = self._get_legacy_external_login_lookup_item(ucr)
        if legacy_item is None:
            return []
        return [legacy_item]

    async def _resolve_lookup_provider_name(
        self, lookup_item: schemas.ExternalLoginLookupItem
    ) -> str | None:
        provider_name = lookup_item.provider.strip() if lookup_item.provider else None
        if provider_name:
            return provider_name

        provider_id = lookup_item.provider_id
        if provider_id is None:
            return None

        if provider_id in self._external_login_provider_name_cache:
            return self._external_login_provider_name_cache[provider_id]

        provider = await models.ExternalLoginProvider.get_by_id(
            self.session, provider_id
        )
        resolved_provider_name = provider.name if provider else None
        self._external_login_provider_name_cache[provider_id] = resolved_provider_name
        return resolved_provider_name

    async def _upsert_identity_external_logins(
        self, user_id: int, ucr: schemas.CreateUserClassRole
    ) -> None:
        identity_lookup_items = self._get_identity_lookup_items(ucr)
        seen: set[tuple[str, str]] = set()

        for lookup_item in identity_lookup_items:
            identifier = lookup_item.identifier.strip()
            if not identifier:
                continue

            provider_name = await self._resolve_lookup_provider_name(lookup_item)
            if not provider_name:
                logger.warning(
                    "Skipping external login upsert for user %s due to unresolved provider (provider_id=%s)",
                    user_id,
                    lookup_item.provider_id,
                )
                continue

            provider_key = provider_name.strip().lower()
            key = (provider_key, identifier)
            if key in seen:
                continue
            seen.add(key)

            await models.ExternalLogin.create_or_update(
                self.session,
                user_id,
                provider_name,
                identifier,
                called_by="AddNewUsers.add_new_users",
            )

    async def _lookup_user_for_ucr(
        self, ucr: schemas.CreateUserClassRole
    ) -> tuple[models.User | None, list[int]]:
        email_lookup = schemas.ExternalLoginLookupItem(
            provider="email",
            identifier=ucr.email.lower(),
        )
        lookup_items = self._get_identity_lookup_items(ucr)
        lookup_items.append(email_lookup)

        try:
            return await models.User.get_by_email_external_logins_priority(
                self.session,
                ucr.email,
                lookup_items,
            )
        except models.AmbiguousExternalLoginLookupError as e:
            logger.exception(
                "Ambiguous external-login lookup during add users; rejecting request. "
                "lookup_index=%s user_ids=%s",
                e.lookup_index,
                e.user_ids,
            )
            raise AddUserException(
                code=409,
                detail=(
                    "Ambiguous external identity lookup matched multiple users "
                    f"for {ucr.email}. Matched user ids: {e.user_ids}. "
                    "Resolve account conflicts and retry."
                ),
            )

    async def _merge_matched_user_ids(
        self,
        user: models.User,
        matched_user_ids: list[int],
        merged_old_user_ids: set[int],
    ) -> models.User:
        canonical_user = user
        for matched_user_id in sorted(set(matched_user_ids)):
            if matched_user_id == canonical_user.id:
                continue
            if matched_user_id in merged_old_user_ids:
                continue
            canonical_user = await merge(
                self.session,
                self.client,
                canonical_user.id,
                matched_user_id,
            )
            merged_old_user_ids.add(matched_user_id)
        return canonical_user

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

    def _check_permissions(self, ucr: schemas.UserClassRole) -> Optional[str]:
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
        if self.new_ucr.lms_tenant or self.new_ucr.lti_class_id:
            enrollment.lms_tenant = self.new_ucr.lms_tenant
            enrollment.lms_type = self.new_ucr.lms_type
            enrollment.lti_class_id = self.new_ucr.lti_class_id
            self.session.add(enrollment)

    async def _create_user_enrollment(
        self,
        user: models.User,
        ucr: schemas.UserClassRole,
        invite_roles: list[str] = [],
    ):
        # External-login identity mapping is handled centrally via
        # _upsert_identity_external_logins before enrollment create/update.
        # Create the user enrollment
        enrollment = await models.UserClassRole.create(
            self.session,
            user.id,
            self.class_id,
            self.new_ucr.lms_tenant,
            self.new_ucr.lms_type,
            None,
            None,
            subscribed_to_summaries=not user.dna_as_join,
            lti_class_id=self.new_ucr.lti_class_id,
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
        if self.new_ucr.lms_tenant:
            users_to_delete = await models.UserClassRole.delete_from_sync_list(
                self.session,
                self.class_id,
                self.newly_synced,
                self.new_ucr.lms_tenant,
                self.new_ucr.lms_type,
            )
        else:
            users_to_delete = await models.UserClassRole.delete_from_sync_list_lti(
                self.session,
                self.class_id,
                self.newly_synced,
                self.new_ucr.lti_class_id,
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

        is_sync_import = (
            bool(self.new_ucr.lms_tenant or self.new_ucr.lti_class_id)
            and not self.new_ucr.is_lti_launch
        )

        # If the request is from LMS, we need to store the newly synced users
        # so we can delete previously synced users that are no longer on the roster
        if is_sync_import:
            self.newly_synced: list[int] = []
            merged_old_user_ids: set[int] = set()

        results: list[schemas.CreateUserResult] = []
        for ucr in self.new_ucr.roles:
            error = self._check_permissions(ucr)
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
            user, matched_user_ids = await self._lookup_user_for_ucr(ucr)
            if user is None:
                user = models.User(
                    email=ucr.email,
                    display_name=ucr.display_name,
                    state=schemas.UserState.UNVERIFIED,
                )
                self.session.add(user)
                await self.session.flush()
                await self.session.refresh(user)

            if is_sync_import:
                user = await self._merge_matched_user_ids(
                    user, matched_user_ids, merged_old_user_ids
                )

            display_name = (
                user.first_name + " " + user.last_name
                if user.first_name and user.last_name
                else user.display_name
                if user.display_name
                else None
            )

            if is_sync_import:
                self.newly_synced.append(user.id)
            if user.id == self.user_id and not self.new_ucr.is_lti_launch:
                # We don't want an LMS sync to change the roles of the user who initiated it
                if is_sync_import:
                    continue
                # An admin cannot add themselves as a student
                if self.is_admin and ucr.roles.student:
                    logger.info("add_users_to_class: AddUserException occurred")
                    results.append(
                        schemas.CreateUserResult(
                            email=ucr.email,
                            display_name=display_name,
                            error="You cannot add yourself as a Member in the Group. Add yourself as a Moderator.",
                        )
                    )
                    continue
                # A teacher cannot downgrade themselves to a student
                if self.is_supervisor and ucr.roles.student:
                    logger.info("add_users_to_class: AddUserException occurred")
                    results.append(
                        schemas.CreateUserResult(
                            email=ucr.email,
                            display_name=display_name,
                            error="You cannot downgrade yourself to a Member in the Group.",
                        )
                    )
                    continue

            # Check if the user is already enrolled in the class
            enrollment = await models.UserClassRole.get(
                self.session, user.id, self.class_id
            )

            is_import_request = bool(
                self.new_ucr.lms_tenant or self.new_ucr.lti_class_id
            )
            is_imported_enrollment = bool(
                enrollment and (enrollment.lms_tenant or enrollment.lti_class_id)
            )
            if is_imported_enrollment and not is_import_request:
                logger.info("add_users_to_class: AddUserException occurred")
                results.append(
                    schemas.CreateUserResult(
                        email=ucr.email,
                        display_name=display_name,
                        error="You cannot manually change the role of an imported user. Please update the user's role in Canvas.",
                    )
                )
                continue

            await self._upsert_identity_external_logins(user.id, ucr)

            invite_roles = []
            for role in ["admin", "teacher", "student"]:
                new_role = (f"user:{user.id}", role, f"class:{self.class_id}")
                if getattr(ucr.roles, role):
                    grants.append(new_role)
                    if not self.new_ucr.silent:
                        invite_roles.append(self.invite_config.formatted_roles[role])
                else:
                    self.revokes.append(new_role)

            if enrollment:
                await self._update_user_enrollment(enrollment, ucr.roles)
                results.append(
                    schemas.CreateUserResult(email=ucr.email, display_name=display_name)
                )
            else:
                await self._create_user_enrollment(user, ucr, invite_roles)
                results.append(
                    schemas.CreateUserResult(email=ucr.email, display_name=display_name)
                )

        # Send emails to new users in the background
        if not self.new_ucr.silent:
            self.send_invites()

        if is_sync_import:
            await self._remove_deleted_users()

        if len(grants) > len(list(set(grants))):
            logger.exception("Duplicate grants detected.")

        await self.client.write_safe(
            grant=list(set(grants)), revoke=list(set(self.revokes))
        )
        return schemas.CreateUserResults(results=results)


class AddNewUsersManual(AddNewUsers):
    def __init__(
        self,
        class_id: str,
        new_ucr: schemas.CreateUserClassRoles,
        request: StateRequest,
        tasks: BackgroundTasks,
        user_id: Optional[int] = None,
    ):
        super().__init__(
            class_id,
            new_ucr,
            user_id or request.state["session"].user.id,
            request.state["db"],
            request.state["authz"],
        )
        self.request = request
        self.tasks = tasks

    def get_now_fn(self) -> NowFn:
        """Get the current time function for the request."""
        app_state = cast(AppState, self.request.app.state)
        return app_state["now"] if "now" in app_state else utcnow

    def send_invites(self):
        nowfn = self.get_now_fn()
        for invite in self.invite_config.invites:
            magic_link = generate_auth_link(
                invite.user_id,
                expiry=86_400 * 7,
                nowfn=nowfn,
                redirect=f"/group/{self.class_id}",
            )
            self.tasks.add_task(
                safe_task,
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
                redirect=f"/group/{self.class_id}",
            )
            send_invite(
                config.email.sender,
                invite,
                magic_link,
                86_400 * 7,
            )
