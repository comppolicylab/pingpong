import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Annotated, Any
import jwt
import openai
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    UploadFile,
    Header,
)
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from .animal_hash import pseudonym
from jwt.exceptions import PyJWTError
from openai.types.beta.assistant_create_params import ToolResources
from openai.types.beta.threads import MessageContentPartParam
from sqlalchemy.sql import func

import pingpong.metrics as metrics
import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.template import email_template as message_template

from .ai import (
    format_instructions,
    generate_name,
    get_openai_client,
    run_thread,
    validate_api_key,
    get_ci_messages_from_step,
)
from .auth import (
    decode_auth_token,
    decode_session_token,
    encode_session_token,
    generate_auth_link,
)
from .authz import Relation
from .config import config
from .errors import sentry
from .files import FILE_TYPES, handle_create_file, handle_delete_file
from .invite import send_invite
from .now import NowFn, utcnow
from .permission import Authz, LoggedIn
from .runs import get_placeholder_ci_calls
from .vector_stores import (
    create_vector_store,
    append_vector_store_files,
    sync_vector_store_files,
    delete_vector_store,
)

logger = logging.getLogger(__name__)

v1 = FastAPI()


def get_now_fn(req: Request) -> NowFn:
    """Get the current time function for the request."""
    return getattr(req.app.state, "now", utcnow)


async def get_openai_client_for_class(request: Request) -> openai.AsyncClient:
    """Get an OpenAI client for the class.

    Requires the class_id to be in the path parameters.
    """
    class_id = request.path_params["class_id"]
    api_key = await models.Class.get_api_key(request.state.db, int(class_id))
    if not api_key:
        raise HTTPException(status_code=401, detail="No API key for class")
    return get_openai_client(api_key)


OpenAIClientDependency = Depends(get_openai_client_for_class)
OpenAIClient = Annotated[openai.AsyncClient, OpenAIClientDependency]


@v1.middleware("http")
async def parse_session_token(request: Request, call_next):
    """Parse the session token from the cookie and add it to the request state."""
    try:
        session_token = request.cookies["session"]
    except KeyError:
        request.state.session = schemas.SessionState(
            status=schemas.SessionStatus.MISSING,
        )
    else:
        try:
            token = decode_session_token(session_token, nowfn=get_now_fn(request))
            user_id = int(token.sub)
            user = await models.User.get_by_id(request.state.db, user_id)
            if not user:
                raise ValueError("User does not exist")

            # Modify user state if necessary
            if user.state == schemas.UserState.UNVERIFIED:
                await user.verify(request.state.db)

            request.state.session = schemas.SessionState(
                token=token,
                status=schemas.SessionStatus.VALID,
                error=None,
                user=user,
                profile=schemas.Profile.from_email(user.email),
            )
        except PyJWTError as e:
            request.state.session = schemas.SessionState(
                status=schemas.SessionStatus.INVALID,
                error=str(e),
            )
        except Exception as e:
            logger.exception("Error parsing session token: %s", e)
            request.state.session = schemas.SessionState(
                status=schemas.SessionStatus.ERROR,
                error=str(e),
            )

    return await call_next(request)


@v1.middleware("http")
async def begin_authz_session(request: Request, call_next):
    """Connect to authorization server."""
    async with config.authz.driver.get_client() as c:
        request.state.authz = c
        response = await call_next(request)
        await c.close()
        return response


@v1.middleware("http")
async def begin_db_session(request: Request, call_next):
    """Create a database session for the request."""
    async with config.db.driver.async_session() as db:
        request.state.db = db
        try:
            result = await call_next(request)
            await db.commit()
            return result
        except Exception as e:
            await db.rollback()
            raise e


@v1.middleware("http")
async def log_request(request: Request, call_next):
    """Log the request."""
    metrics.in_flight.inc(app=config.public_url)
    start_time = time.monotonic()
    result = None
    try:
        result = await call_next(request)
        return result
    finally:
        metrics.in_flight.dec(app=config.public_url)
        status = result.status_code if result else 500
        duration = time.monotonic() - start_time
        metrics.api_requests.inc(
            app=config.public_url,
            route=request.url.path,
            method=request.method,
            status=status,
        )
        metrics.api_request_duration.observe(
            duration,
            app=config.public_url,
            route=request.url.path,
            method=request.method,
            status=status,
        )
        if config.development:
            logger.debug(
                "Request %s %s %s %s",
                request.method,
                request.url.path,
                status,
                duration,
            )


@v1.get("/config", dependencies=[Depends(Authz("admin"))])
def get_config(request: Request):
    d = config.dict()
    for k in d.get("auth", {}).get("secret_keys", []):
        k["key"] = "******"
    if "key" in d.get("authz", {}):
        d["authz"]["key"] = "******"
    if "password" in d.get("db", {}):
        d["db"]["password"] = "******"
    if "webhook" in d.get("support", {}):
        d["support"]["webhook"] = "******"
    return {"config": config.dict(), "headers": dict(request.headers)}


@v1.get(
    "/authz/audit",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.InspectAuthz,
)
async def inspect_authz(request: Request, subj: str, obj: str, rel: str):
    subj_type_, _, subj_id_ = subj.partition(":")
    obj_type_, _, obj_id_ = obj.partition(":")
    try:
        result: schemas.InspectAuthzResult | None = None
        if obj_id_:
            verdict = await request.state.authz.test(subj, rel, obj)
            result = schemas.InspectAuthzTestResult(
                verdict=verdict,
            )
        else:
            ids = await request.state.authz.list(subj, rel, obj)
            result = schemas.InspectAuthzListResult(
                list=ids,
            )
    except Exception as e:
        result = schemas.InspectAuthzErrorResult(error=str(e))

    return schemas.InspectAuthz(
        subject=schemas.AuthzEntity(id=int(subj_id_), type=subj_type_),
        relation=rel,
        object=schemas.AuthzEntity(
            id=int(obj_id_) if obj_id_ else None, type=obj_type_
        ),
        result=result,
    )


@v1.post(
    "/authz/audit",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def manage_authz(data: schemas.ManageAuthzRequest, request: Request):
    await request.state.authz.write(grant=data.grant, revoke=data.revoke)
    return {"status": "ok"}


@v1.post("/login/magic", response_model=schemas.GenericStatus)
async def login(body: schemas.MagicLoginRequest, request: Request):
    """Provide a magic link to the auth endpoint."""
    # Get the email from the request.
    email = body.email
    # Look up the user by email
    user = await models.User.get_by_email(request.state.db, email)
    # Throw an error if the user does not exist.
    if not user:
        # In dev we can auto-create the user as a super-admin
        if config.auth.autopromote_on_login:
            if not config.development:
                raise RuntimeError("Cannot autopromote in non-dev mode")
            user = await models.User.get_or_create_by_email(request.state.db, email)
            user.super_admin = True
            request.state.db.add(user)
            await request.state.authz.create_root_user(user.id)
        else:
            raise HTTPException(status_code=401, detail="User does not exist")

    nowfn = get_now_fn(request)
    magic_link = generate_auth_link(user.id, expiry=86_400, nowfn=nowfn)

    message = message_template.substitute(
        {
            "title": "Welcome back!",
            "subtitle": "Click the button below to log in to PingPong. No password required. It&#8217;s secure and easy.",
            "type": "login link",
            "cta": "Login to PingPong",
            "underline": "",
            "link": magic_link,
            "email": email,
            "legal_text": "because you requested a login link from PingPong",
        }
    )

    await config.email.sender.send(
        email,
        "Log back in to PingPong",
        message,
    )

    return {"status": "ok"}


@v1.get("/auth")
async def auth(request: Request, response: Response):
    # Get the `token` query parameter from the request and store it in variable.
    dest = request.query_params.get("redirect", "/")
    stok = request.query_params.get("token")
    nowfn = get_now_fn(request)
    try:
        auth_token = decode_auth_token(stok, nowfn=nowfn)
    except jwt.exceptions.PyJWTError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Create a token for the user with more information.
    session_dur = 86_400 * 30
    session_token = encode_session_token(
        int(auth_token.sub), expiry=session_dur, nowfn=nowfn
    )

    response = RedirectResponse(config.url(dest), status_code=303)
    response.set_cookie(
        key="session",
        value=session_token,
        max_age=session_dur,
    )
    return response


@v1.get(
    "/institutions",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Institutions,
)
async def list_institutions(request: Request, role: str = "can_view"):
    ids = await request.state.authz.list(
        f"user:{request.state.session.user.id}", role, "institution"
    )
    inst = await models.Institution.get_all_by_id(request.state.db, ids)
    return {"institutions": inst}


@v1.post(
    "/institution",
    dependencies=[Depends(Authz("can_create_institution"))],
    response_model=schemas.Institution,
)
async def create_institution(create: schemas.CreateInstitution, request: Request):
    inst = await models.Institution.create(request.state.db, create)
    await request.state.authz.grant(
        request.state.authz.root,
        "parent",
        f"institution:{inst.id}",
    )
    return inst


@v1.get(
    "/institution/{institution_id}",
    dependencies=[Depends(Authz("can_view", "institution:{institution_id}"))],
    response_model=schemas.Institution,
)
async def get_institution(institution_id: str, request: Request):
    return await models.Institution.get_by_id(request.state.db, int(institution_id))


@v1.get(
    "/institution/{institution_id}/classes",
    dependencies=[Depends(Authz("can_view", "institution:{institution_id}"))],
    response_model=schemas.Classes,
)
async def get_institution_classes(institution_id: str, request: Request):
    classes = await models.Class.get_by_institution(
        request.state.db, int(institution_id)
    )
    return {"classes": classes}


@v1.post(
    "/institution/{institution_id}/class",
    dependencies=[Depends(Authz("can_create_class", "institution:{institution_id}"))],
    response_model=schemas.Class,
)
async def create_class(
    institution_id: str, create: schemas.CreateClass, request: Request
):
    new_class = await models.Class.create(request.state.db, int(institution_id), create)

    # Create an entry for the creator as the owner
    ucr = models.UserClassRole(
        user_id=request.state.session.user.id,
        class_id=new_class.id,
    )
    request.state.db.add(ucr)

    grants = [
        (f"institution:{institution_id}", "parent", f"class:{new_class.id}"),
        (f"user:{request.state.session.user.id}", "admin", f"class:{new_class.id}"),
    ]

    if not new_class.private:
        grants.append(
            (
                f"class:{new_class.id}#supervisor",
                "can_manage_threads",
                f"class:{new_class.id}",
            )
        )
        grants.append(
            (
                f"class:{new_class.id}#admin",
                "can_manage_assistants",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_create_assistant:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_create_assistants",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_publish_assistant:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_publish_assistants",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_publish_thread:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_publish_threads",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_upload_class_file:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_upload_class_files",
                f"class:{new_class.id}",
            )
        )

    await request.state.authz.write(grant=grants)

    return new_class


@v1.get(
    "/classes",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Classes,
)
async def get_my_classes(request: Request):
    ids = await request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "can_view",
        "class",
    )
    classes = await models.Class.get_all_by_id(request.state.db, ids)
    return {"classes": classes}


@v1.get(
    "/class/{class_id}",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.Class,
)
async def get_class(class_id: str, request: Request):
    return await models.Class.get_by_id(request.state.db, int(class_id))


@v1.get(
    "/class/{class_id}/upload_info",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.FileUploadSupport,
)
async def get_class_upload_info(class_id: str, request: Request):
    return {
        "types": FILE_TYPES,
        "allow_private": True,
        "private_file_max_size": config.upload.private_file_max_size,
        "class_file_max_size": config.upload.class_file_max_size,
    }


@v1.put(
    "/class/{class_id}",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.Class,
)
async def update_class(class_id: str, update: schemas.UpdateClass, request: Request):
    cls = await models.Class.update(request.state.db, int(class_id), update)

    grants = []
    revokes = []
    can_create_asst = (
        f"class:{class_id}#student",
        "can_create_assistants",
        f"class:{class_id}",
    )
    can_pub_asst = (
        f"class:{class_id}#student",
        "can_publish_assistants",
        f"class:{class_id}",
    )
    can_pub_thread = (
        f"class:{class_id}#student",
        "can_publish_threads",
        f"class:{class_id}",
    )
    can_upload_class_file = (
        f"class:{class_id}#student",
        "can_upload_class_files",
        f"class:{class_id}",
    )
    supervisor_as_can_manage_threads = (
        f"class:{class_id}#supervisor",
        "can_manage_threads",
        f"class:{class_id}",
    )
    admin_as_can_manage_assistants = (
        f"class:{class_id}#admin",
        "can_manage_assistants",
        f"class:{class_id}",
    )

    if cls.any_can_create_assistant:
        grants.append(can_create_asst)
    else:
        revokes.append(can_create_asst)

    if cls.any_can_publish_assistant:
        grants.append(can_pub_asst)
    else:
        revokes.append(can_pub_asst)

    if cls.any_can_publish_thread:
        grants.append(can_pub_thread)
    else:
        revokes.append(can_pub_thread)

    if cls.any_can_upload_class_file:
        grants.append(can_upload_class_file)
    else:
        revokes.append(can_upload_class_file)

    if cls.private:
        revokes.append(supervisor_as_can_manage_threads)
        revokes.append(admin_as_can_manage_assistants)
    else:
        grants.append(supervisor_as_can_manage_threads)
        grants.append(admin_as_can_manage_assistants)

    await request.state.authz.write_safe(grant=grants, revoke=revokes)

    return cls


@v1.get(
    "/class/{class_id}/users",
    dependencies=[Depends(Authz("can_view_users", "class:{class_id}"))],
    response_model=schemas.ClassUsers,
)
async def list_class_users(
    class_id: str, request: Request, limit: int = 20, offset: int = 0, search: str = ""
):
    if offset < 0:
        raise HTTPException(status_code=400, detail="Offset must be non-negative")
    if limit < 1:
        raise HTTPException(status_code=400, detail="Limit must be positive")
    # Get hard-coded relations from DB. Everyone with an explicit role in the class.
    # NOTE: this is *not* necessarily everyone who has permission to view the class;
    # it's usually a subset, due to inherited permissions from parent objects.
    # To get the full list of everyone with access, we need to use the `/audit` endpoint.
    users = list[models.UserClassRole]()

    batch = list[Relation]()
    async for u in models.Class.get_members(
        request.state.db, int(class_id), limit=limit, offset=offset, search=search
    ):
        users.append(u)
        for role in ["admin", "teacher", "student"]:
            batch.append((f"user:{u.user_id}", role, f"class:{class_id}"))

    total, results = await asyncio.gather(
        models.Class.get_member_count(request.state.db, int(class_id), search=search),
        request.state.authz.check(batch),
    )

    class_users = list[schemas.ClassUser]()
    for i, u in enumerate(users):
        class_users.append(
            schemas.ClassUser(
                id=u.user_id,
                first_name=u.user.first_name,
                last_name=u.user.last_name,
                display_name=u.user.display_name,
                email=u.user.email,
                state=u.user.state,
                roles=schemas.ClassUserRoles(
                    admin=results[i * 3],
                    teacher=results[i * 3 + 1],
                    student=results[i * 3 + 2],
                ),
                explanation=[[]],
            )
        )

    return {"users": class_users, "limit": limit, "offset": offset, "total": total}


@v1.post(
    "/class/{class_id}/user",
    dependencies=[Depends(Authz("can_manage_users", "class:{class_id}"))],
    response_model=schemas.UserClassRoles,
)
async def add_users_to_class(
    class_id: str,
    new_ucr: schemas.CreateUserClassRoles,
    request: Request,
    tasks: BackgroundTasks,
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
                status_code=403, detail="Lacking permission to add teachers"
            )

        user = await models.User.get_or_create_by_email(request.state.db, ucr.email)
        if is_admin and user.id == request.state.session.user.id:
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
                )
            )
            request.state.db.add(existing)
        else:
            # Make sure the user exists...
            added = await models.UserClassRole.create(
                request.state.db,
                user.id,
                cid,
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


@v1.put(
    "/class/{class_id}/user/{user_id}/role",
    dependencies=[Depends(Authz("can_manage_users", "class:{class_id}"))],
    response_model=schemas.UserClassRole,
)
async def update_user_class_role(
    class_id: str, user_id: str, update: schemas.UpdateUserClassRole, request: Request
):
    cid = int(class_id)
    uid = int(user_id)

    # Weird things will happen if someone tries to modify their own role.
    if uid == request.state.session.user.id:
        raise HTTPException(status_code=400, detail="Cannot modify your own role")

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
    new_idx = ordered_roles.index(update.role)

    # If they already have more permissions than we do, we can't downgrade them
    if their_primary_idx < my_primary_idx:
        raise HTTPException(
            status_code=403, detail="Lacking permission to manage this user"
        )

    # If the new permission is higher than our own, we can't upgrade them
    if my_primary_idx > new_idx:
        raise HTTPException(
            status_code=403, detail=f"Missing permission to manage '{update.role}' role"
        )

    existing = await models.UserClassRole.get(request.state.db, uid, cid)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found in class")

    grants = list[Relation]()
    revokes = list[Relation]()

    # Grant the new role and revoke all others. The new role might be None.
    if update.role:
        grants.append((f"user:{uid}", update.role, f"class:{cid}"))
    for role in ["admin", "teacher", "student"]:
        if role != update.role:
            revokes.append((f"user:{uid}", role, f"class:{cid}"))

    # Save new role info to the database.
    await request.state.authz.write_safe(grant=grants, revoke=revokes)

    return schemas.UserClassRole(
        user_id=existing.user_id,
        class_id=existing.class_id,
        # NOTE(jnu): This assumes the write to the authz server was successful,
        # and doesn't double check. Worst case, if a write silently failed,
        # the UI will be in an inconsistent state until the page is reloaded.
        roles=schemas.ClassUserRoles(
            admin=update.role == "admin",
            teacher=update.role == "teacher",
            student=update.role == "student",
        ),
    )


@v1.delete(
    "/class/{class_id}/user/{user_id}",
    dependencies=[Depends(Authz("admin", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def remove_user_from_class(class_id: str, user_id: str, request: Request):
    cid = int(class_id)
    uid = int(user_id)

    if uid == request.state.session.user.id:
        raise HTTPException(
            status_code=403, detail="Cannot remove yourself from a class"
        )

    existing = await models.UserClassRole.get(request.state.db, uid, cid)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found in class")

    await models.UserClassRole.delete(request.state.db, uid, cid)

    revokes = list[Relation]()
    for role in ["admin", "teacher", "student"]:
        revokes.append((f"user:{uid}", role, f"class:{cid}"))

    await request.state.authz.write_safe(revoke=revokes)

    return {"status": "ok"}


@v1.put(
    "/class/{class_id}/api_key",
    dependencies=[Depends(Authz("admin", "class:{class_id}"))],
    response_model=schemas.ApiKey,
)
async def update_class_api_key(
    class_id: str, update: schemas.UpdateApiKey, request: Request
):
    existing_key = await models.Class.get_api_key(request.state.db, int(class_id))
    if existing_key == update.api_key:
        return {"api_key": existing_key}
    elif not existing_key:
        if not await validate_api_key(update.api_key):
            raise HTTPException(
                status_code=400,
                detail="Invalid API key provided. Please try again.",
            )
        await models.Class.update_api_key(
            request.state.db, int(class_id), update.api_key
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="API key already exists. Delete it first to create a new one.",
        )
    return {"api_key": update.api_key}


@v1.get(
    "/class/{class_id}/api_key",
    dependencies=[Depends(Authz("can_view_api_key", "class:{class_id}"))],
    response_model=schemas.ApiKey,
)
async def get_class_api_key(class_id: str, request: Request):
    api_key = await models.Class.get_api_key(request.state.db, int(class_id))
    return {"api_key": api_key}


@v1.get(
    "/class/{class_id}/models",
    dependencies=[Depends(Authz("can_create_assistants", "class:{class_id}"))],
    response_model=schemas.AssistantModels,
)
async def list_class_models(
    class_id: str, request: Request, openai_client: OpenAIClient
):
    """List available models for the class assistants."""
    all_models = await openai_client.models.list()
    # Models known to work with file_search, which we always have on.
    known_models: dict[str, schemas.AssistantModelDict] = {
        "gpt-4o": {
            "sort_order": 0,
            "is_latest": True,
            "supports_vision": True,
            "description": "The latest GPT-4o model, OpenAI's most advanced model.",
        },
        "gpt-4-turbo": {
            "sort_order": 1,
            "is_latest": True,
            "supports_vision": True,
            "description": "The latest GPT-4 Turbo model.",
        },
        "gpt-4-turbo-preview": {
            "sort_order": 2,
            "is_latest": True,
            "supports_vision": False,
            "description": "The latest GPT-4 Turbo preview model.",
        },
        "gpt-3.5-turbo": {
            "sort_order": 3,
            "is_latest": True,
            "supports_vision": False,
            "description": "The latest GPT-3.5 Turbo model.",
        },
        "gpt-4o-2024-05-13": {
            "sort_order": 4,
            "is_latest": False,
            "supports_vision": True,
            "description": "GPT-4o initial release version, 2x faster than GPT-4 Turbo.",
        },
        "gpt-4-turbo-2024-04-09": {
            "sort_order": 5,
            "is_latest": False,
            "supports_vision": True,
            "description": "GPT-4 Turbo with Vision model.",
        },
        "gpt-4-0125-preview": {
            "sort_order": 6,
            "is_latest": False,
            "supports_vision": False,
            "description": 'GPT-4 Turbo preview model with a fix for "laziness," where the model doesn\'t complete a task.',
        },
        "gpt-4-1106-preview": {
            "sort_order": 7,
            "is_latest": False,
            "supports_vision": False,
            "description": "GPT-4 Turbo preview model with improved instruction following, reproducible outputs, and more.",
        },
        "gpt-3.5-turbo-0125": {
            "sort_order": 8,
            "is_latest": False,
            "supports_vision": False,
            "description": "GPT-3.5 Turbo model with higher accuracy at responding in requested formats.",
        },
        "gpt-3.5-turbo-1106": {
            "sort_order": 9,
            "is_latest": False,
            "supports_vision": False,
            "description": "GPT-3.5 Turbo model with improved instruction following, reproducible outputs, and more.",
        },
    }
    # Only GPT-* models are currently available for assistants.
    # TODO - there might be other filters we need.
    filtered = [
        {
            "id": m.id,
            "created": datetime.fromtimestamp(m.created),
            "owner": m.owned_by,
            "description": known_models[m.id]["description"],
            "is_latest": known_models[m.id]["is_latest"],
            "supports_vision": known_models[m.id]["supports_vision"],
        }
        for m in all_models.data
        if m.id in known_models.keys()
    ]
    filtered.sort(key=lambda x: known_models[x["id"]]["sort_order"])
    return {"models": filtered}


@v1.get(
    "/class/{class_id}/thread/{thread_id}",
    dependencies=[
        Depends(
            Authz("can_view", "thread:{thread_id}"),
        )
    ],
    response_model=schemas.ThreadWithMeta,
)
async def get_thread(
    class_id: str, thread_id: str, request: Request, openai_client: OpenAIClient
):
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    messages, assistant, runs_result = await asyncio.gather(
        openai_client.beta.threads.messages.list(
            thread.thread_id, limit=20, order="desc"
        ),
        models.Assistant.get_by_id(request.state.db, thread.assistant_id),
        openai_client.beta.threads.runs.list(thread.thread_id, limit=1, order="desc"),
    )
    last_run = [r async for r in runs_result]

    if messages.data:
        users = {str(u.id): u for u in thread.users}

    for message in messages.data:
        user_id = message.metadata.pop("user_id", None)
        if not user_id:
            continue
        message.metadata["is_current_user"] = user_id == str(request.state.session.user.id)
        message.metadata["name"] = "Anonymous User" if thread.private else pseudonym(thread, users[user_id])

    placeholder_ci_calls = []
    if "code_interpreter" in thread.tools_available:
        placeholder_ci_calls = await get_placeholder_ci_calls(
            request.state.db,
            messages.data[0].assistant_id if messages.data[0].assistant_id else "None",
            thread.thread_id,
            thread.id,
            messages.data[-1].created_at,
        )

    thread.assistant_names = {assistant.id: assistant.name}
    thread.user_names = [
                "Me"
                if u.id == request.state.session.user.id
                else pseudonym(thread, u)
                if not thread.private
                else "Anonymous User"
                for u in thread.users
            ]

    return {
        "thread": thread,
        "model": assistant.model,
        "tools_available": thread.tools_available,
        "run": last_run[0] if last_run else None,
        "messages": list(messages.data),
        "limit": 20,
        "ci_messages": placeholder_ci_calls,
    }


@v1.get(
    "/class/{class_id}/thread/{thread_id}/ci_messages",
    dependencies=[
        Depends(
            Authz("can_view", "thread:{thread_id}"),
        )
    ],
    response_model=schemas.CodeInterpreterMessages,
)
async def get_ci_messages(
    class_id: str,
    thread_id: str,
    request: Request,
    openai_client: OpenAIClient,
    openai_thread_id: str,
    run_id: str,
    step_id: str,
):
    messages = await get_ci_messages_from_step(
        openai_client, openai_thread_id, run_id, step_id
    )

    return {
        "ci_messages": messages,
    }


@v1.get(
    "/class/{class_id}/thread/{thread_id}/messages",
    dependencies=[
        Depends(
            Authz("can_view", "thread:{thread_id}"),
        )
    ],
    response_model=schemas.ThreadMessages,
)
async def list_thread_messages(
    class_id: str,
    thread_id: str,
    request: Request,
    openai_client: OpenAIClient,
    limit: int = 20,
    before: str | None = None,
):
    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="Limit must be positive",
        )

    limit = min(limit, 100)

    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    messages = await openai_client.beta.threads.messages.list(
        thread.thread_id, limit=limit, order="asc", before=before
    )

    if messages.data:
        users = {u.id: u.created for u in thread.users}

    for message in messages.data:
        user_id = message.metadata.pop("user_id", None)
        if not user_id:
            continue
        message.metadata["is_current_user"] = user_id == str(request.state.session.user.id)
        message.metadata["name"] = "Anonymous User" if thread.private else pseudonym(thread, users[user_id])

    placeholder_ci_calls = []
    # Only run the extra steps if code_interpreter is available
    if "code_interpreter" in thread.tools_available and messages.data:
        placeholder_ci_calls = await get_placeholder_ci_calls(
            request.state.db,
            messages.data[0].assistant_id if messages.data[0].assistant_id else "None",
            thread.thread_id,
            thread.id,
            messages.data[0].created_at,
            messages.data[-1].created_at,
        )

    return {
        "messages": list(messages.data),
        "ci_messages": placeholder_ci_calls,
        "limit": limit,
    }


@v1.get(
    "/class/{class_id}/thread/{thread_id}/last_run",
    dependencies=[
        Depends(Authz("can_view", "thread:{thread_id}")),
    ],
    response_model=schemas.ThreadRun,
)
async def get_last_run(
    class_id: str,
    thread_id: str,
    request: Request,
    openai_client: OpenAIClient,
    block: bool = True,
):
    TIMEOUT = 60  # seconds
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))

    # Streaming is not supported right now, so we need to poll to get the last run.
    # https://platform.openai.com/docs/assistants/how-it-works/runs-and-run-steps
    runs = [
        r
        async for r in await openai_client.beta.threads.runs.list(
            thread.thread_id, limit=1, order="desc"
        )
    ]

    if not runs:
        return {"thread": thread, "run": None}

    last_run = runs[0]

    if not block:
        return {"thread": thread, "run": last_run}

    t0 = time.monotonic()
    while last_run.status not in {"completed", "failed", "expired", "cancelled"}:
        if time.monotonic() - t0 > TIMEOUT:
            raise HTTPException(
                status_code=504, detail="Timeout waiting for run to complete"
            )
        # Poll until the run is complete.
        await asyncio.sleep(1)
        try:
            last_run = await openai_client.beta.threads.runs.retrieve(
                last_run.id, thread_id=thread.thread_id
            )
        except openai.APIConnectionError as e:
            logger.error("Error connecting to OpenAI: %s", e)
            # Contine polling

    return {"thread": thread, "run": last_run}


@v1.get(
    "/threads/recent",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Threads,
)
async def list_recent_threads(
    request: Request, limit: int = 5, before: str | None = None
):
    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="Limit must be positive",
        )

    # Parse `before` timestamp if it was given
    current_latest_time: datetime | None = (
        datetime.fromisoformat(before) if before else None
    )
    thread_ids = await request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "party",
        "thread",
    )

    threads = await models.Thread.get_n_by_id(
        request.state.db,
        request.state.session.user.id,
        thread_ids,
        limit,
        before=current_latest_time,
    )

    return {"threads": threads}


@v1.get(
    "/threads",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Threads,
)
async def list_all_threads(
    request: Request,
    limit: int = 20,
    before: str | None = None,
    private: bool | None = None,
    class_id: int | None = None,
):
    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="Limit must be positive",
        )

    # Parse `before` timestamp if it was given
    current_latest_time: datetime | None = (
        datetime.fromisoformat(before) if before else None
    )
    thread_ids = await request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "can_view",
        "thread",
    )
    threads = await models.Thread.get_n_by_id(
        request.state.db,
        request.state.session.user.id,
        thread_ids,
        limit,
        before=current_latest_time,
        private=private,
        class_id=class_id,
    )

    return {"threads": threads}


@v1.get(
    "/class/{class_id}/threads",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.Threads,
)
async def list_threads(
    class_id: str, request: Request, limit: int = 20, before: str | None = None
):
    if limit < 1:
        raise HTTPException(
            status_code=400,
            detail="Limit must be positive",
        )

    # Parse `before` timestamp if it was given
    current_latest_time: datetime | None = (
        datetime.fromisoformat(before) if before else None
    )
    can_view_coro = request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "can_view",
        "thread",
    )
    in_class_coro = request.state.authz.list(
        f"class:{class_id}",
        "parent",
        "thread",
    )
    can_view, in_class = await asyncio.gather(can_view_coro, in_class_coro)
    thread_ids = list(set(can_view) & set(in_class))
    threads = await models.Thread.get_n_by_id(
        request.state.db,
        request.state.session.user.id,
        thread_ids,
        limit,
        before=current_latest_time,
    )

    return {"threads": threads}


@v1.post(
    "/class/{class_id}/thread",
    dependencies=[Depends(Authz("can_create_thread", "class:{class_id}"))],
    response_model=schemas.Thread,
)
async def create_thread(
    class_id: str,
    req: schemas.CreateThread,
    request: Request,
    openai_client: OpenAIClient,
):
    parties = list[models.User]()
    tool_resources: ToolResources = {}
    vector_store_id = None
    vector_store_object_id = None

    if req.file_search_file_ids:
        vector_store_id, vector_store_object_id = await create_vector_store(
            request.state.db,
            openai_client,
            class_id,
            req.file_search_file_ids,
            type=schemas.VectorStoreType.THREAD,
        )
        tool_resources["file_search"] = {"vector_store_ids": [vector_store_id]}

    if req.code_interpreter_file_ids:
        tool_resources["code_interpreter"] = {"file_ids": req.code_interpreter_file_ids}

    messageContent: MessageContentPartParam = [{"type": "text", "text": req.message}]

    if req.vision_file_ids:
        [
            messageContent.append({"type": "image_file", "image_file": {"file_id": id}})
            for id in req.vision_file_ids
        ]

    name, thread, parties = await asyncio.gather(
        generate_name(openai_client, req.message),
        openai_client.beta.threads.create(
            messages=[
                {
                    "metadata": {"user_id": str(request.state.session.user.id)},
                    "role": "user",
                    "content": messageContent,
                }
            ],
            tool_resources=tool_resources,
        ),
        models.User.get_all_by_id(request.state.db, req.parties),
    )

    tools_export = req.model_dump(include={"tools_available"})

    new_thread = {
        "class_id": int(class_id),
        "name": name,
        "private": True if parties else False,
        "users": parties or [],
        "thread_id": thread.id,
        "assistant_id": req.assistant_id,
        "vector_store_id": vector_store_object_id,
        "code_interpreter_file_ids": req.code_interpreter_file_ids or [],
        "image_file_ids": req.vision_file_ids or [],
        "tools_available": json.dumps(tools_export["tools_available"] or []),
        "version": 2,
    }

    result: None | models.Thread = None
    try:
        result = await models.Thread.create(
            request.state.db, request.state.session.user.id, new_thread
        )

        grants = [
            (f"class:{class_id}", "parent", f"thread:{result.id}"),
        ] + [(f"user:{p.id}", "party", f"thread:{result.id}") for p in parties]
        await request.state.authz.write(grant=grants)

        return result
    except Exception as e:
        logger.error("Error creating thread: %s", e)
        if vector_store_id:
            await openai_client.beta.vector_stores.delete(vector_store_id)
        await openai_client.beta.threads.delete(thread.id)
        if result:
            # Delete users-threads mapping
            for user in result.users:
                result.users.remove(user)
            await result.delete(request.state.db)
        raise e


@v1.post(
    "/class/{class_id}/thread/{thread_id}/run",
    dependencies=[
        Depends(Authz("can_participate", "thread:{thread_id}")),
    ],
)
async def create_run(
    class_id: str,
    thread_id: str,
    request: Request,
    openai_client: OpenAIClient,
):
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    asst = await models.Assistant.get_by_id(request.state.db, thread.assistant_id)

    stream = run_thread(
        openai_client,
        thread_id=thread.thread_id,
        assistant_id=asst.assistant_id,
        message=[],
    )

    return StreamingResponse(stream, media_type="text/event-stream")


@v1.post(
    "/class/{class_id}/thread/{thread_id}",
    dependencies=[
        Depends(Authz("can_participate", "thread:{thread_id}")),
    ],
)
async def send_message(
    class_id: str,
    thread_id: str,
    data: schemas.NewThreadMessage,
    request: Request,
    openai_client: OpenAIClient,
):
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    asst = await models.Assistant.get_by_id(request.state.db, thread.assistant_id)

    tool_resources: ToolResources = {}

    if data.file_search_file_ids:
        if thread.vector_store_id:
            # Vector store already exists, update
            vectore_store_id = await append_vector_store_files(
                request.state.db,
                openai_client,
                thread.vector_store_id,
                data.file_search_file_ids,
            )
            tool_resources["file_search"] = {"vector_store_ids": [vectore_store_id]}
        else:
            # Store doesn't exist, create a new one
            vector_store_id, vector_store_object_id = await create_vector_store(
                request.state.db,
                openai_client,
                class_id,
                data.file_search_file_ids,
                type=schemas.VectorStoreType.THREAD,
            )
            thread.vector_store_id = vector_store_object_id
            tool_resources["file_search"] = {"vector_store_ids": [vector_store_id]}

    if data.code_interpreter_file_ids:
        existing_file_ids = [
            file_id
            async for file_id in models.Thread.get_file_ids_by_id(
                request.state.db, thread.id
            )
        ]

        await models.Thread.add_code_interpeter_files(
            request.state.db, thread.id, data.code_interpreter_file_ids
        )

        tool_resources["code_interpreter"] = {
            "file_ids": existing_file_ids + data.code_interpreter_file_ids
        }

    messageContent: MessageContentPartParam = [{"type": "text", "text": data.message}]

    if data.vision_file_ids:
        await models.Thread.add_image_files(
            request.state.db, thread.id, data.vision_file_ids
        )
        [
            messageContent.append({"type": "image_file", "image_file": {"file_id": id}})
            for id in data.vision_file_ids
        ]

    try:
        await openai_client.beta.threads.update(
            thread.thread_id, tool_resources=tool_resources
        )
    except openai.BadRequestError as e:
        raise HTTPException(400, e.message or "OpenAI rejected this request")

    thread.updated = func.now()
    request.state.db.add(thread)

    metrics.inbound_messages.inc(
        app=config.public_url,
        class_=int(class_id),
        user=request.state.session.user.id,
        thread=thread.thread_id,
    )

    # Create a generator that will stream chunks to the client.
    stream = run_thread(
        openai_client,
        thread_id=thread.thread_id,
        assistant_id=asst.assistant_id,
        message=messageContent,
        metadata={"user_id": str(request.state.session.user.id)},
    )
    return StreamingResponse(stream, media_type="text/event-stream")


@v1.post(
    "/class/{class_id}/thread/{thread_id}/publish",
    dependencies=[
        Depends(Authz("can_publish", "thread:{thread_id}")),
    ],
    response_model=schemas.GenericStatus,
)
async def publish_thread(class_id: str, thread_id: str, request: Request):
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    thread.private = False
    request.state.db.add(thread)
    await request.state.authz.write_safe(
        grant=[(f"class:{class_id}#member", "can_view", f"thread:{thread_id}")]
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/thread/{thread_id}/publish",
    dependencies=[
        Depends(Authz("can_publish", "thread:{thread_id}")),
    ],
    response_model=schemas.GenericStatus,
)
async def unpublish_thread(class_id: str, thread_id: str, request: Request):
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    thread.private = True
    request.state.db.add(thread)
    await request.state.authz.write_safe(
        revoke=[(f"class:{class_id}#member", "can_view", f"thread:{thread_id}")]
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/thread/{thread_id}",
    dependencies=[Depends(Authz("can_delete", "thread:{thread_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_thread(
    class_id: str, thread_id: str, request: Request, openai_client: OpenAIClient
):
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    revokes = [(f"class:{class_id}", "parent", f"thread:{thread_id}")] + [
        (f"user:{u.id}", "party", f"thread:{thread_id}") for u in thread.users
    ]
    await thread.delete(request.state.db)
    await openai_client.beta.threads.delete(thread.thread_id)
    await request.state.authz.write_safe(revoke=revokes)

    return {"status": "ok"}


@v1.post(
    "/class/{class_id}/file",
    dependencies=[Depends(Authz("can_upload_class_files", "class:{class_id}"))],
    response_model=schemas.File,
)
async def create_file(
    class_id: str, request: Request, upload: UploadFile, openai_client: OpenAIClient
):
    if upload.size > config.upload.class_file_max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size is {config.upload.class_file_max_size} bytes.",
        )

    return await handle_create_file(
        request.state.db,
        request.state.authz,
        openai_client,
        upload=upload,
        class_id=int(class_id),
        uploader_id=request.state.session.user.id,
        private=False,
    )


@v1.post(
    "/class/{class_id}/user/{user_id}/file",
    dependencies=[Depends(Authz("can_upload_user_files", "class:{class_id}"))],
    response_model=schemas.File,
)
async def create_user_file(
    class_id: str,
    user_id: str,
    request: Request,
    upload: UploadFile,
    openai_client: OpenAIClient,
    purpose: schemas.FileUploadPurpose = Header(None, alias="X-Upload-Purpose"),
) -> schemas.File:
    if upload.size > config.upload.private_file_max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size is {config.upload.private_file_max_size} bytes.",
        )

    return await handle_create_file(
        request.state.db,
        request.state.authz,
        openai_client,
        upload=upload,
        class_id=int(class_id),
        uploader_id=request.state.session.user.id,
        private=True,
        purpose=purpose,
    )


@v1.delete(
    "/class/{class_id}/file/{file_id}",
    dependencies=[Depends(Authz("can_delete", "class_file:{file_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_file(
    class_id: str, file_id: str, request: Request, openai_client: OpenAIClient
):
    return await handle_delete_file(
        request.state.db, request.state.authz, openai_client, int(file_id)
    )


@v1.delete(
    "/class/{class_id}/user/{user_id}/file/{file_id}",
    dependencies=[
        Depends(Authz("can_delete", "user_file:{file_id}")),
    ],
    response_model=schemas.GenericStatus,
)
async def delete_user_file(
    class_id: str,
    user_id: str,
    file_id: str,
    request: Request,
    openai_client: OpenAIClient,
):
    return await handle_delete_file(
        request.state.db, request.state.authz, openai_client, int(file_id)
    )


@v1.get(
    "/class/{class_id}/files",
    dependencies=[Depends(Authz("member", "class:{class_id}"))],
    response_model=schemas.Files,
)
async def list_files(class_id: str, request: Request):
    ids = await request.state.authz.list(
        f"user:{request.state.session.user.id}", "can_view", "class_file"
    )
    class_ids = await request.state.authz.list(
        f"class:{class_id}",
        "parent",
        "class_file",
    )

    file_ids = list(set(ids) & set(class_ids))
    files = await models.File.get_all_by_id(request.state.db, file_ids)
    return {"files": files}


@v1.get(
    "/class/{class_id}/assistants",
    dependencies=[Depends(Authz("member", "class:{class_id}"))],
    response_model=schemas.Assistants,
)
async def list_assistants(class_id: str, request: Request):
    # Only return assistants that are in the class and are visible to the current user.
    all_for_class = await models.Assistant.get_by_class_id(
        request.state.db, int(class_id)
    )
    filters = await request.state.authz.check(
        [
            (
                f"user:{request.state.session.user.id}",
                "can_view",
                f"assistant:{a.id}",
            )
            for a in all_for_class
        ]
    )
    assts = [a for a, f in zip(all_for_class, filters) if f]

    creator_ids = {a.creator_id for a in assts}
    creators = await models.User.get_all_by_id(request.state.db, list(creator_ids))
    creator_perms = await request.state.authz.check(
        [
            (
                f"user:{id_}",
                "supervisor",
                f"class:{class_id}",
            )
            for id_ in creator_ids
        ]
    )
    endorsed_creators = {id_ for id_, perm in zip(creator_ids, creator_perms) if perm}

    ret_assistants = list[schemas.Assistant]()
    for asst in assts:
        cur_asst = schemas.Assistant.from_orm(asst)
        has_elevated_permissions = await request.state.authz.test(
            f"user:{request.state.session.user.id}", "can_edit", f"assistant:{asst.id}"
        )
        if asst.hide_prompt and not has_elevated_permissions:
            cur_asst.instructions = ""

        # For now, "endorsed" creators are published assistants that were
        # created by a teacher or admin.
        #
        # TODO(jnu): separate this into an explicit category where teachers
        # can mark any public assistant as "endorsed."
        # https://github.com/stanford-policylab/pingpong/issues/226
        if asst.published and asst.creator_id in endorsed_creators:
            cur_asst.endorsed = True

        ret_assistants.append(cur_asst)

    return {
        "assistants": ret_assistants,
        "creators": {c.id: c for c in creators},
    }


@v1.post(
    "/class/{class_id}/assistant",
    dependencies=[Depends(Authz("can_create_assistants", "class:{class_id}"))],
    response_model=schemas.Assistant,
)
async def create_assistant(
    class_id: str,
    req: schemas.CreateAssistant,
    request: Request,
    openai_client: OpenAIClient,
):
    class_id_int = int(class_id)
    creator_id = request.state.session.user.id

    if req.published:
        if not await request.state.authz.test(
            f"user:{creator_id}", "can_publish_assistants", f"class:{class_id}"
        ):
            raise HTTPException(403, "You lack permission to publish an assistant.")

    tool_resources: ToolResources = {}
    vector_store_object_id = None

    if req.file_search_file_ids:
        vector_store_id, vector_store_object_id = await create_vector_store(
            request.state.db,
            openai_client,
            class_id,
            req.file_search_file_ids,
            type=schemas.VectorStoreType.ASSISTANT,
        )
        tool_resources["file_search"] = {"vector_store_ids": [vector_store_id]}

    del req.file_search_file_ids

    if req.code_interpreter_file_ids:
        tool_resources["code_interpreter"] = {"file_ids": req.code_interpreter_file_ids}

    try:
        new_asst = await openai_client.beta.assistants.create(
            instructions=format_instructions(req.instructions, use_latex=req.use_latex),
            model=req.model,
            tools=req.tools,
            metadata={"class_id": class_id, "creator_id": str(creator_id)},
            tool_resources=tool_resources,
        )
    except openai.BadRequestError as e:
        raise HTTPException(400, e.message or "OpenAI rejected this request")

    try:
        asst = await models.Assistant.create(
            request.state.db,
            req,
            class_id=class_id_int,
            user_id=creator_id,
            assistant_id=new_asst.id,
            vector_store_id=vector_store_object_id,
            version=2,
        )

        grants = [
            (f"class:{class_id}", "parent", f"assistant:{asst.id}"),
            (f"user:{creator_id}", "owner", f"assistant:{asst.id}"),
        ]

        if req.published:
            grants.append(
                (f"class:{class_id}#member", "can_view", f"assistant:{asst.id}"),
            )

        await request.state.authz.write(grant=grants)

        return asst
    except Exception as e:
        if vector_store_object_id:
            await openai_client.beta.vector_stores.delete(vector_store_id)
        await openai_client.beta.assistants.delete(new_asst.id)
        raise e


@v1.put(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[Depends(Authz("can_edit", "assistant:{assistant_id}"))],
    response_model=schemas.Assistant,
)
async def update_assistant(
    class_id: str,
    assistant_id: str,
    req: schemas.UpdateAssistant,
    request: Request,
    openai_client: OpenAIClient,
):
    # Get the existing assistant.
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    grants = list[Relation]()
    revokes = list[Relation]()

    # Check additional permissions
    if not asst.published and req.published:
        if not await request.state.authz.test(
            f"user:{request.state.session.user.id}",
            "can_publish",
            f"assistant:{assistant_id}",
        ):
            raise HTTPException(
                status_code=403,
                detail="You are not allowed to publish assistants for this class.",
            )

    if not req.model_dump():
        return asst

    openai_update: dict[str, Any] = {}
    # Update the assistant
    tool_resources: ToolResources = {}

    if req.code_interpreter_file_ids is not None:
        tool_resources["code_interpreter"] = {"file_ids": req.code_interpreter_file_ids}
        asst.code_interpreter_files = await models.File.get_all_by_file_id(
            request.state.db, req.code_interpreter_file_ids
        )

    if req.file_search_file_ids is not None:
        # Files will need to be stored in a vector store
        if asst.vector_store_id:
            # Vector store already exists, update
            vectore_store_id = await sync_vector_store_files(
                request.state.db,
                openai_client,
                asst.vector_store_id,
                req.file_search_file_ids,
            )
            tool_resources["file_search"] = {"vector_store_ids": [vectore_store_id]}
        else:
            # Store doesn't exist, create a new one
            vectore_store_id, vector_store_object_id = await create_vector_store(
                request.state.db,
                openai_client,
                class_id,
                req.file_search_file_ids,
                type=schemas.VectorStoreType.THREAD,
            )
            asst.vector_store_id = vector_store_object_id
            tool_resources["file_search"] = {"vector_store_ids": [vectore_store_id]}
    else:
        # No files stored in vector store, remove it
        if asst.vector_store_id:
            await delete_vector_store(
                request.state.db, openai_client, asst.vector_store_id
            )
            tool_resources["file_search"] = {}

    openai_update["tool_resources"] = tool_resources
    if req.use_latex is not None:
        asst.use_latex = req.use_latex
    if req.hide_prompt is not None:
        asst.hide_prompt = req.hide_prompt
    if req.instructions is not None:
        if not req.instructions:
            raise HTTPException(400, "Instructions cannot be empty.")
        asst.instructions = req.instructions
    if req.model is not None:
        openai_update["model"] = req.model
        asst.model = req.model
    if req.description is not None:
        asst.description = req.description
    if req.tools is not None:
        openai_update["tools"] = req.tools
        asst.tools = json.dumps([t.model_dump() for t in req.tools])
    if req.published is not None:
        ptuple = (f"class:{class_id}#member", "can_view", f"assistant:{asst.id}")
        if req.published:
            asst.published = func.now()
            grants.append(ptuple)
        else:
            asst.published = None
            revokes.append(ptuple)

    if req.name is not None:
        asst.name = req.name

    await models.Thread.update_tools_available(request.state.db, asst.id, asst.tools)
    request.state.db.add(asst)
    await request.state.db.flush()
    await request.state.db.refresh(asst)

    if not asst.instructions:
        raise HTTPException(500, "Instructions cannot be empty.")
    openai_update["instructions"] = format_instructions(
        asst.instructions, use_latex=asst.use_latex
    )

    try:
        await openai_client.beta.assistants.update(
            assistant_id=asst.assistant_id, **openai_update
        )
    except openai.BadRequestError as e:
        raise HTTPException(400, e.message or "OpenAI rejected this request")

    await request.state.authz.write_safe(grant=grants, revoke=revokes)

    return asst


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[Depends(Authz("can_delete", "assistant:{assistant_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_assistant(
    class_id: str, assistant_id: str, request: Request, openai_client: OpenAIClient
):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    await asst.delete(request.state.db)
    await openai_client.beta.assistants.delete(asst.assistant_id)
    # TODO clean up grants
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/assistant/{assistant_id}/files",
    dependencies=[Depends(Authz("can_view", "assistant:{assistant_id}"))],
    response_model=schemas.AssistantFilesResponse,
)
async def get_assistant_files(
    class_id: str,
    assistant_id: str,
    request: Request,
):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    file_search_files = []
    if asst.vector_store_id:
        file_search_files = await models.VectorStore.get_files_by_id(
            request.state.db, asst.vector_store_id
        )
    code_interpreter_files = asst.code_interpreter_files
    return {
        "files": {
            "file_search_files": file_search_files,
            "code_interpreter_files": code_interpreter_files,
        }
    }


@v1.get(
    "/class/{class_id}/thread/{thread_id}/image/{file_id}",
    dependencies=[Depends(Authz("can_view", "thread:{thread_id}"))],
)
async def get_image(file_id: str, request: Request, openai_client: OpenAIClient):
    response = await openai_client.files.with_raw_response.retrieve_content(file_id)
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail="An error occurred fetching the requested file",
        )
    return Response(content=response.content, media_type="image/png")


@v1.get(
    "/class/{class_id}/thread/{thread_id}/file/{file_id}",
    dependencies=[Depends(Authz("can_view", "thread:{thread_id}"))],
)
async def download_file(
    class_id: str,
    thread_id: str,
    file_id: str,
    request: Request,
    openai_client: OpenAIClient,
):
    response = await openai_client.files.with_raw_response.retrieve_content(file_id)
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail="An error occurred fetching the requested file",
        )
    # Usually we can just proxy headers from the OpenAI response, but make sure we have
    # defaults set just in case.
    media_type = response.headers.get("content-type", "application/octet-stream")
    disposition = response.headers.get(
        "content-disposition", f"attachment; filename={file_id}"
    )
    headers = {
        "Content-Type": media_type,
        "Content-Disposition": disposition,
    }
    return Response(content=response.content, headers=headers)


@v1.get(
    "/me",
)
async def get_me(request: Request):
    """Get the session information."""
    return request.state.session


@v1.put(
    "/me",
    dependencies=[Depends(LoggedIn())],
)
async def update_me(request: Request, update: schemas.UpdateUserInfo):
    """Update the user profile."""
    return await models.User.update_info(
        request.state.db, request.state.session.user.id, update
    )


@v1.get(
    "/me/grants/list",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GrantsList,
)
async def get_grants_list(rel: str, obj: str, request: Request):
    """List objects for which user has a specific relation."""
    sub = f"user:{request.state.session.user.id}"
    results = await request.state.authz.list(
        sub,
        rel,
        obj,
    )
    return {
        "subject_type": "user",
        "subject_id": request.state.session.user.id,
        "relation": rel,
        "target_type": obj,
        "target_ids": results,
    }


@v1.post(
    "/me/grants",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Grants,
)
async def get_grants(query: schemas.GrantsQuery, request: Request):
    checks = list[Relation]()
    user_id = f"user:{request.state.session.user.id}"
    for grant in query.grants:
        target = f"{grant.target_type}:{grant.target_id}"
        checks.append(
            (user_id, grant.relation, target),
        )

    results = await request.state.authz.check(checks)
    return {
        "grants": [
            schemas.GrantDetail(
                request=query.grants[i],
                verdict=results[i],
            )
            for i in range(len(query.grants))
        ],
    }


@v1.get(
    "/support",
    response_model=schemas.Support,
)
async def get_support(request: Request):
    """Get the support information."""
    return {
        "blurb": config.support.blurb(),
        "can_post": bool(config.support.driver),
    }


@v1.post(
    "/support",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def post_support(
    req: schemas.SupportRequest,
    request: Request,
):
    """Post a support request."""
    if not config.support.driver:
        raise HTTPException(status_code=403, detail="Support is not available.")

    try:
        await config.support.driver.post(
            req, env=config.public_url, ts=datetime.utcnow()
        )
        return {"status": "ok"}
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail="Failed to post support request.")


async def lifespan(app: FastAPI):
    """Run services in the background."""
    if not await config.db.driver.exists():
        logger.warning("Creating a new database since none exists.")
        await config.db.driver.create()
        await config.db.driver.init(models.Base)

    logger.info("Configuring authorization ...")
    await config.authz.driver.init()

    with sentry(), metrics.metrics():
        yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    """Handle exceptions."""
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
        )


app.mount("/api/v1", v1)


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}
