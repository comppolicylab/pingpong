from pingpong.authz.openfga import OpenFgaAuthzClient
import pingpong.models as models
import pingpong.schemas as schemas

from fastapi import BackgroundTasks, HTTPException, Request
from starlette.background import BackgroundTasks as BackgroundTasksCron
from sqlalchemy.ext.asyncio import AsyncSession
from .auth import generate_auth_link
from .authz import Relation
from .config import config
from .invite import send_invite
from .now import NowFn, utcnow


def get_now_fn(req: Request | None) -> NowFn:
    """Get the current time function for the request."""
    if req is None:
        return utcnow
    return getattr(req.app.state, "now", utcnow)


async def add_new_users(
    class_id: str,
    new_ucr: schemas.CreateUserClassRoles,
    request: Request,
    tasks: BackgroundTasks,
    ignore_self: bool = False,
    from_canvas: bool = False,
):
    cid = int(class_id)
    class_ = await models.Class.get_by_id(request.state.db, cid)
    result: list[schemas.UserClassRole] = []
    new_: list[schemas.CreateInvite] = []

    grants = list[Relation]()
    revokes = list[Relation]()

    is_admin = await request.state.authz.test(
        f"user:{request.state.session.user.id}", "admin", f"class:{class_id}"
    )

    formatted_roles = {
        "admin": "an Administrator",
        "teacher": "a Moderator",
        "student": "a Member",
    }

    user_display_name = await models.User.get_display_name(
        request.state.db, request.state.session.user.id
    )

    for ucr in new_ucr.roles:
        if not is_admin and ucr.roles.admin:
            raise HTTPException(
                status_code=403, detail="Lacking permission to add admins"
            )

        if not is_admin and ucr.roles.teacher:
            raise HTTPException(
                status_code=403, detail="Lacking permission to add moderators"
            )

        user = await models.User.get_or_create_by_email(request.state.db, ucr.email)
        if is_admin and user.id == request.state.session.user.id:
            if ignore_self:
                continue
            if not ucr.roles.admin:
                raise HTTPException(
                    status_code=403, detail="Cannot demote yourself from admin"
                )

        existing = await models.UserClassRole.get(request.state.db, user.id, cid)
        new_roles = []
        for role in ["admin", "teacher", "student"]:
            if getattr(ucr.roles, role):
                grants.append((f"user:{user.id}", role, f"class:{cid}"))
                new_roles.append(formatted_roles[role])
            else:
                revokes.append((f"user:{user.id}", role, f"class:{cid}"))

        if existing:
            result.append(
                schemas.UserClassRole(
                    user_id=existing.user_id,
                    class_id=existing.class_id,
                    roles=ucr.roles,
                    from_canvas=from_canvas,
                )
            )
            existing.from_canvas = from_canvas
            request.state.db.add(existing)
        else:
            # Make sure the user exists...
            added = await models.UserClassRole.create(
                request.state.db,
                user.id,
                cid,
                from_canvas,
            )
            new_.append(
                schemas.CreateInvite(
                    user_id=user.id,
                    email=user.email,
                    class_name=class_.name,
                    inviter_name=user_display_name,
                    formatted_role=", ".join(new_roles) if new_roles else None,
                )
            )
            result.append(
                schemas.UserClassRole(
                    user_id=added.user_id,
                    class_id=added.class_id,
                    roles=ucr.roles,
                    from_canvas=from_canvas,
                )
            )

    # Send emails to new users in the background
    nowfn = get_now_fn(request)
    for invite in new_:
        magic_link = generate_auth_link(invite.user_id, expiry=86_400 * 7, nowfn=nowfn)
        tasks.add_task(
            send_invite,
            config.email.sender,
            invite,
            magic_link,
            new_ucr.silent,
        )

    await request.state.authz.write_safe(grant=grants, revoke=revokes)

    return {"roles": result}


async def add_new_users_cron(
    class_id: str,
    user_id: int,
    session: AsyncSession,
    client: OpenFgaAuthzClient | None,
    new_ucr: schemas.CreateUserClassRoles,
    ignore_self: bool = True,
    from_canvas: bool = True,
):
    if not client:
        raise HTTPException(status_code=500, detail="Authz client not available")

    cid = int(class_id)
    class_ = await models.Class.get_by_id(session, cid)
    result: list[schemas.UserClassRole] = []
    new_: list[schemas.CreateInvite] = []

    grants = list[Relation]()
    revokes = list[Relation]()

    is_admin = await client.test(f"user:{user_id}", "admin", f"class:{class_id}")

    formatted_roles = {
        "admin": "an Administrator",
        "teacher": "a Moderator",
        "student": "a Member",
    }

    user_display_name = await models.User.get_display_name(session, user_id)

    for ucr in new_ucr.roles:
        if not is_admin and ucr.roles.admin:
            raise HTTPException(
                status_code=403, detail="Lacking permission to add admins"
            )

        if not is_admin and ucr.roles.teacher:
            raise HTTPException(
                status_code=403, detail="Lacking permission to add moderators"
            )

        user = await models.User.get_or_create_by_email(session, ucr.email)
        if is_admin and user.id == user_id:
            if ignore_self:
                continue
            if not ucr.roles.admin:
                raise HTTPException(
                    status_code=403, detail="Cannot demote yourself from admin"
                )

        existing = await models.UserClassRole.get(session, user.id, cid)
        new_roles = []
        for role in ["admin", "teacher", "student"]:
            if getattr(ucr.roles, role):
                grants.append((f"user:{user.id}", role, f"class:{cid}"))
                new_roles.append(formatted_roles[role])
            else:
                revokes.append((f"user:{user.id}", role, f"class:{cid}"))

        if existing:
            result.append(
                schemas.UserClassRole(
                    user_id=existing.user_id,
                    class_id=existing.class_id,
                    roles=ucr.roles,
                    from_canvas=from_canvas,
                )
            )
            existing.from_canvas = from_canvas
            session.add(existing)
        else:
            # Make sure the user exists...
            added = await models.UserClassRole.create(
                session,
                user.id,
                cid,
                from_canvas,
            )
            new_.append(
                schemas.CreateInvite(
                    user_id=user.id,
                    email=user.email,
                    class_name=class_.name,
                    inviter_name=user_display_name,
                    formatted_role=", ".join(new_roles) if new_roles else None,
                )
            )
            result.append(
                schemas.UserClassRole(
                    user_id=added.user_id,
                    class_id=added.class_id,
                    roles=ucr.roles,
                    from_canvas=from_canvas,
                )
            )

    # Reverts to utcnow since we have no request
    nowfn = get_now_fn(None)
    # Send emails to new users in the background
    tasks = BackgroundTasksCron()
    for invite in new_:
        magic_link = generate_auth_link(invite.user_id, expiry=86_400 * 7, nowfn=nowfn)
        tasks.add_task(
            send_invite,
            config.email.sender,
            invite,
            magic_link,
            new_ucr.silent,
        )

    await client.write_safe(grant=grants, revoke=revokes)

    return {"roles": result}
