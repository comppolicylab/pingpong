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


def get_now_fn(req: Request) -> NowFn:
    """Get the current time function for the request."""
    return getattr(req.app.state, "now", utcnow)


async def add_new_users(
    class_id: str,
    new_ucr: schemas.CreateUserClassRoles,
    ignore_self: bool = False,
    request: Request | None = None,
    tasks: BackgroundTasks | None = None,
    user_id: int | None = None,
    session: AsyncSession | None = None,
    client: OpenFgaAuthzClient | None = None,
    cron: bool = False,
):
    if cron and (not user_id or not session or not client):
        raise HTTPException(status_code=400, detail="Missing cron arguments")
    elif not cron and (not request or not tasks):
        raise HTTPException(status_code=400, detail="Missing request arguments")

    cid = int(class_id)

    session_ = session if session else request.state.db if request else None
    user_id_ = (
        user_id if user_id else request.state.session.user.id if request else None
    )
    client_ = client if client else request.state.authz if request else None
    class_ = await models.Class.get_by_id(session_, cid)
    result: list[schemas.UserClassRole] = []
    new_: list[schemas.CreateInvite] = []

    grants = list[Relation]()
    revokes = list[Relation]()

    is_admin = await client_.test(f"user:{user_id_}", "admin", f"class:{class_id}")

    formatted_roles = {
        "admin": "an Administrator",
        "teacher": "a Moderator",
        "student": "a Member",
    }

    user_display_name = await models.User.get_display_name(
        session_,
        user_id_,
    )

    from_canvas = new_ucr.from_canvas or False

    if from_canvas:
        newly_synced: list = []
    for ucr in new_ucr.roles:
        if not is_admin and ucr.roles.admin:
            raise HTTPException(
                status_code=403, detail="Lacking permission to add admins"
            )

        if not is_admin and ucr.roles.teacher:
            raise HTTPException(
                status_code=403, detail="Lacking permission to add moderators"
            )

        user = await models.User.get_or_create_by_email(session_, ucr.email)
        if from_canvas:
            newly_synced.append(user.id)
        if is_admin and user.id == user_id_:
            if ignore_self:
                continue
            if not ucr.roles.admin:
                raise HTTPException(
                    status_code=403, detail="Cannot demote yourself from admin"
                )

        existing = await models.UserClassRole.get(session_, user.id, cid)
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
            session_.add(existing)
        else:
            # Make sure the user exists...
            added = await models.UserClassRole.create(
                session_,
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
    nowfn = get_now_fn(request) if not cron else utcnow
    tasks_ = tasks if not cron else BackgroundTasksCron()
    for invite in new_:
        magic_link = generate_auth_link(invite.user_id, expiry=86_400 * 7, nowfn=nowfn)
        tasks_.add_task(
            send_invite,
            config.email.sender,
            invite,
            magic_link,
            86_400 * 7,
            new_ucr.silent,
        )

    if from_canvas:
        users_to_delete = await models.UserClassRole.delete_from_sync_list(
            session_, int(class_id), newly_synced
        )
        await delete_canvas_permissions(client_, users_to_delete, class_id)
    await client_.write_safe(grant=grants, revoke=revokes)

    return {"roles": result}


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
