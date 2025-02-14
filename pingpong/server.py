import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Annotated, Any, Optional, Union
from aiohttp import ClientResponseError
import jwt
import openai
import humanize
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import PositiveInt

from pingpong.ai_models import upgrade_assistants_model
from pingpong.artifacts import ArtifactStoreError
from pingpong.bg_tasks import safe_task
from pingpong.emails import (
    parse_addresses,
    revalidate_email_addresses,
    validate_email_addresses,
)
from pingpong.stats import get_statistics
from pingpong.summary import send_class_summary_to_user_task
from .animal_hash import process_threads, pseudonym, user_names
from jwt.exceptions import PyJWTError
from openai.types.beta.assistant_create_params import ToolResources
from openai.types.beta.threads.message_create_params import Attachment
from openai.types.beta.threads import MessageContentPartParam
from sqlalchemy.sql import func, delete, update

import pingpong.metrics as metrics
import pingpong.models as models
import pingpong.schemas as schemas
from .auth import TimeException, authn_method_for_email
from .template import email_template as message_template
from .time import convert_seconds
from .saml import get_saml2_client, get_saml2_settings, get_saml2_attrs

from .ai import (
    REASONING_EFFORT_MAP,
    GetOpenAIClientException,
    export_class_threads_anonymized,
    export_threads_multiple_classes,
    format_instructions,
    get_openai_client_by_class_id,
    get_thread_conversation_name,
    get_initial_thread_conversation_name,
    run_thread,
    validate_api_key,
    get_ci_messages_from_step,
    get_azure_model_deployment_name_equivalent,
    get_details_from_api_error,
)
from .auth import (
    decode_auth_token,
    decode_session_token,
    generate_auth_link,
    redirect_with_session,
)
from .authz import Relation
from .config import config
from .canvas import (
    CanvasAccessException,
    CanvasException,
    CanvasInvalidTokenException,
    CanvasWarning,
    LightweightCanvasClient,
    ManualCanvasClient,
    decode_canvas_token,
    get_canvas_config,
)
from .errors import sentry
from .files import (
    FILE_TYPES,
    FileNotFoundException,
    generate_vision_image_descriptions_string,
    handle_create_file,
    handle_delete_file,
    handle_delete_files,
)
from .now import NowFn, utcnow
from .permission import Authz, LoggedIn
from .runs import get_placeholder_ci_calls
from .vector_stores import (
    add_vector_store_files_to_db,
    create_vector_store,
    delete_vector_store,
    delete_vector_store_db_returning_file_ids,
    sync_vector_store_files,
    delete_vector_store_db,
    delete_vector_store_oai,
)
from .users import (
    AddNewUsersManual,
    AddUserException,
    CheckUserPermissionException,
    check_permissions,
    delete_canvas_permissions,
)
from .merge import list_all_permissions, merge

logger = logging.getLogger(__name__)

v1 = FastAPI()


def get_now_fn(req: Request) -> NowFn:
    """Get the current time function for the request."""
    return getattr(req.app.state, "now", utcnow)


OpenAIClientType = Union[openai.AsyncClient, openai.AsyncAzureOpenAI]


async def get_openai_client_for_class(request: Request) -> OpenAIClientType:
    """Get an OpenAI client for the class.

    Requires the class_id to be in the path parameters.
    """
    class_id = request.path_params["class_id"]
    try:
        return await get_openai_client_by_class_id(request.state.db, int(class_id))
    except GetOpenAIClientException as e:
        raise HTTPException(status_code=e.code, detail=e.detail)


OpenAIClientDependency = Depends(get_openai_client_for_class)
OpenAIClient = Annotated[OpenAIClientType, OpenAIClientDependency]


class UserNotFoundException(Exception):
    def __init__(self, detail: str = "", user_id: str = ""):
        self.user_id = user_id
        self.detail = detail


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
                raise UserNotFoundException(
                    "We couldn't locate your account. Please try logging in again.",
                    token.sub,
                )
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
        except TimeException as e:
            request.state.session = schemas.SessionState(
                status=schemas.SessionStatus.INVALID,
                error=e.detail,
            )
        except UserNotFoundException as e:
            logger.warning(f"parse_session_token: User not found: {e.user_id}")
            request.state.session = schemas.SessionState(
                status=schemas.SessionStatus.ERROR,
                error=e.detail,
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
    async with config.db.driver.async_session_with_args(pool_pre_ping=True)() as db:
        request.state.db = db
        try:
            result = await call_next(request)
            status_code = getattr(result, "status_code", 0)
            if not status_code or status_code >= 400:
                await db.rollback()
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
        if obj_id_ and subj_id_:
            logger.info(f"Inspecting authz for {subj} {rel} {obj}")
            verdict = await request.state.authz.test(subj, rel, obj)
            result = schemas.InspectAuthzTestResult(
                verdict=verdict,
            )
        elif subj_id_:
            ids = await request.state.authz.list(subj, rel, obj)
            result = schemas.InspectAuthzListResult(
                list=ids,
            )
        elif obj_id_ and subj_type_ == "user":
            ids = await request.state.authz.list_entities(obj, rel, subj_type_)
            result = schemas.InspectAuthzListResult(
                list=ids,
            )
        else:
            raise HTTPException(status_code=400, detail="Bad request")
    except Exception as e:
        result = schemas.InspectAuthzErrorResult(error=str(e))

    return schemas.InspectAuthz(
        subject=schemas.AuthzEntity(
            id=int(subj_id_) if subj_id_ else None, type=subj_type_
        ),
        relation=rel,
        object=schemas.AuthzEntity(
            id=int(obj_id_) if obj_id_ else None, type=obj_type_
        ),
        result=result,
    )


@v1.get("/authz/audit_all", dependencies=[Depends(Authz("admin"))])
async def list_all_user_permissions(request: Request, user_id: str):
    return await list_all_permissions(request.state.authz, int(user_id))


@v1.post(
    "/authz/audit",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def manage_authz(data: schemas.ManageAuthzRequest, request: Request):
    await request.state.authz.write(grant=data.grant, revoke=data.revoke)
    return {"status": "ok"}


@v1.post("/login/sso/saml/acs", response_model=schemas.GenericStatus)
async def login_sso_saml_acs(provider: str, request: Request):
    """SAML login assertion consumer service."""
    try:
        sso_config = get_saml2_settings(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail="SSO provider not found")
    saml_client = await get_saml2_client(sso_config, request)
    saml_client.process_response()

    errors = saml_client.get_errors()
    if errors:
        raise HTTPException(status_code=400, detail=errors)

    if not saml_client.is_authenticated():
        raise HTTPException(status_code=401, detail="SAML authentication failed")

    attrs = get_saml2_attrs(sso_config, saml_client)

    # Create user if missing. Update if already exists.
    user = await models.User.get_by_email_sso(
        request.state.db, attrs.email, provider, attrs.identifier
    )
    if not user:
        user = models.User(
            email=attrs.email,
        )

    # Update user info
    user.email = attrs.email
    user.first_name = attrs.first_name
    user.last_name = attrs.last_name
    user.display_name = attrs.name
    user.state = schemas.UserState.VERIFIED

    # Save user to DB
    request.state.db.add(user)
    await request.state.db.flush()
    await request.state.db.refresh(user)

    # Add external login and get accounts to merge
    await models.ExternalLogin.create_or_update(
        request.state.db, user.id, provider=provider, identifier=attrs.identifier
    )
    user_ids = await models.ExternalLogin.accounts_to_merge(
        request.state.db, user.id, provider=provider, identifier=attrs.identifier
    )

    # Merge accounts
    for uid in user_ids:
        await merge(request.state.db, request.state.authz, user.id, uid)

    url = "/"
    if "RelayState" in saml_client._request_data["get_data"]:
        url = saml_client._request_data["get_data"]["RelayState"]
    elif "RelayState" in saml_client._request_data["post_data"]:
        url = saml_client._request_data["post_data"]["RelayState"]
    next_url = saml_client.redirect_to(url)
    return redirect_with_session(next_url, user.id, nowfn=get_now_fn(request))


@v1.get("/login/sso")
async def login_sso(provider: str, request: Request):
    # Find the SSO method
    try:
        sso_config = get_saml2_settings(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail="SSO provider not found")

    if sso_config.protocol == "saml":
        saml_client = await get_saml2_client(sso_config, request)
        dest = request.query_params.get("redirect", "/")
        return RedirectResponse(saml_client.login(dest))
    else:
        raise HTTPException(
            status_code=501, detail=f"SSO protocol {sso_config.protocol} not supported"
        )


@v1.get(
    "/user",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.User,
)
async def get_user_by_email(email: str, request: Request):
    _email = email.lower().strip()
    user = await models.User.get_by_email_sso(request.state.db, _email, "email", _email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@v1.get(
    "/user/{user_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.User,
)
async def get_user(user_id: str, request: Request):
    user = await models.User.get_by_id(request.state.db, int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@v1.get(
    "/user/{user_id}/email",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.ExternalLogins,
)
async def get_secondary_emails(user_id: str, request: Request):
    user = await models.User.get_by_id(request.state.db, int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    external_logins = await models.ExternalLogin.get_secondary_emails_by_user_id(
        request.state.db, user.id
    )
    return schemas.ExternalLogins(
        external_logins=external_logins,
        user_id=user.id,
    )


@v1.post(
    "/user/{user_id}/email",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def add_email_to_user(user_id: str, email: str, request: Request):
    _new_email = email.lower().strip()
    email_verification = parse_addresses(_new_email)

    if not email_verification[0].valid:
        raise HTTPException(status_code=400, detail="Invalid new email address.")

    user = await models.User.get_by_id(request.state.db, int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        is_new_or_updated = await models.ExternalLogin.create_or_update(
            request.state.db, user.id, provider="email", identifier=_new_email
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if is_new_or_updated:
        nowfn = get_now_fn(request)
        magic_link = generate_auth_link(
            user.id,
            expiry=86_400 * 7,
            nowfn=nowfn,
        )
        message_to_new = message_template.substitute(
            {
                "title": "Your PingPong account was updated",
                "subtitle": f"Per your request, we added <a href='mailto:{_new_email}'>{_new_email}</a> as a login email to your PingPong account. You can now use it along with your primary email address (<a href='mailto:{user.email}'>{user.email}</a>) to log in.</p><p>Click the button below to log in to PingPong. No password required. It&#8217;s secure and easy.",
                "type": "login link",
                "cta": "Login to PingPong",
                "underline": "<strong>If you did not request this change, please contact us immediately at <a href='mailto:pingpong-help@hks.harvard.edu'>pingpong-help@hks.harvard.edu</a>.</strong>",
                "expires": convert_seconds(86_400 * 7),
                "link": magic_link,
                "email": _new_email,
                "legal_text": "because you requested an update to the login information of your PingPong account",
            }
        )

        message_to_current = message_template.substitute(
            {
                "title": "Your PingPong account was updated",
                "subtitle": f"Per your request, we added <a href='mailto:{_new_email}'>{_new_email}</a> as a login email to your PingPong account. You can now use it along with your primary email address (<a href='mailto:{user.email}'>{user.email}</a>) to log in.</p><p>Click the button below to log in to PingPong. No password required. It&#8217;s secure and easy.",
                "type": "login link",
                "cta": "Login to PingPong",
                "underline": "<strong>If you did not request this change, please contact us immediately at <a href='mailto:pingpong-help@hks.harvard.edu'>pingpong-help@hks.harvard.edu</a>.</strong>",
                "expires": convert_seconds(86_400 * 7),
                "link": magic_link,
                "email": user.email,
                "legal_text": "because you requested an update to the login information of your PingPong account",
            }
        )

        await config.email.sender.send(
            _new_email,
            "A login email was added to your PingPong account",
            message_to_new,
        )

        await config.email.sender.send(
            user.email,
            "A login email was added to your PingPong account",
            message_to_current,
        )

    return {"status": "ok"}


@v1.delete(
    "/user/{user_id}/email/{email}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def delete_email_from_user(user_id: str, email: str, request: Request):
    user = await models.User.get_by_id(request.state.db, int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        await models.ExternalLogin.delete_secondary_email(
            request.state.db, user.id, email=email
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "ok"}


@v1.post(
    "/user/merge",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def merge_users(
    old_user_id: PositiveInt, new_user_id: PositiveInt, request: Request
):
    await merge(request.state.db, request.state.authz, new_user_id, old_user_id)
    return {"status": "ok"}


@v1.post("/login/magic", response_model=schemas.GenericStatus)
async def login_magic(body: schemas.MagicLoginRequest, request: Request):
    """Provide a magic link to the auth endpoint."""
    # First figure out if this email domain is even allowed to use magic auth.
    # If not, we deny the request and point to another place they can log in.
    login_config = authn_method_for_email(config.auth.authn_methods, body.email)
    if not login_config:
        raise HTTPException(
            status_code=400, detail="No login method found for email domain"
        )
    if login_config.method == "sso":
        raise HTTPException(
            status_code=403,
            detail=f"/api/v1/login/sso?provider={login_config.provider}&redirect={body.forward}",
        )
    elif login_config.method != "magic_link":
        raise HTTPException(
            status_code=501, detail=f"Login method {login_config.method} not supported"
        )

    # Get the email from the request.
    email = body.email
    # Look up the user by email
    user = await models.User.get_by_email_sso(request.state.db, email, "email", email)
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
    magic_link = generate_auth_link(
        user.id, expiry=login_config.expiry, nowfn=nowfn, redirect=body.forward
    )

    message = message_template.substitute(
        {
            "title": "Welcome back!",
            "subtitle": "Click the button below to log in to PingPong. No password required. It&#8217;s secure and easy.",
            "type": "login link",
            "cta": "Login to PingPong",
            "underline": "",
            "expires": convert_seconds(login_config.expiry),
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


@v1.get("/auth/canvas")
async def auth_canvas(request: Request):
    """Canvas OAuth2 callback. For now, this defaults to using the Harvard instance.

    This endpoint is called by Canvas after the user has authenticated.
    We exchange the code for an access token and then redirect to the
    destination URL with the user's session token.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    try:
        canvas_token = decode_canvas_token(state, nowfn=get_now_fn(request))
        user_id = int(canvas_token.user_id)
        class_id = int(canvas_token.class_id)
        lms_tenant = canvas_token.lms_tenant
    except Exception:
        return RedirectResponse(
            config.url("/?error_code=1"),
            status_code=303,
        )

    if error:
        class_id = int(canvas_token.class_id)
        match error:
            case (
                "invalid_request"
                | "unauthorized_client"
                | "unsupported_response_type"
                | "invalid_scope"
            ):
                return RedirectResponse(
                    config.url(f"/group/{class_id}/manage?error_code=1"),
                    status_code=303,
                )
            case "access_denied":
                return RedirectResponse(
                    config.url(f"/group/{class_id}/manage?error_code=2"),
                    status_code=303,
                )
            case "server_error" | "temporarily_unavailable":
                return RedirectResponse(
                    config.url(f"/group/{class_id}/manage?error_code=3"),
                    status_code=303,
                )
            case _:
                return RedirectResponse(
                    config.url(f"/group/{class_id}/manage?error_code=4"),
                    status_code=303,
                )
    try:
        canvas_settings = get_canvas_config(lms_tenant)
    except ValueError:
        canvas_settings = None

    if not code or not canvas_settings or user_id != request.state.session.user.id:
        return RedirectResponse(
            config.url(f"/group/{class_id}/manage?error_code=4"),
            status_code=303,
        )

    async with LightweightCanvasClient(
        canvas_settings,
        class_id,
        request,
    ) as client:
        return await client.complete_initial_auth(code)


@v1.get("/auth")
async def auth(request: Request):
    """Continue the auth flow based on a JWT in the query params.

    If the token is valid, determine the correct authn method based on the user.
    If the user is allowed to use magic link auth, they'll be authed automatically
    by this endpoint. If they have to go through SSO, they'll be redirected to the
    SSO login endpoint.

    Raises:
        HTTPException(401): If the token is invalid.
        HTTPException(500): If there is an runtime error decoding the token.
        HTTPException(404): If the user ID is not found.
        HTTPException(501): If we don't support the auth method for the user.

    Returns:
        RedirectResponse: Redirect either to the SSO login endpoint or to the destination.
    """
    dest = request.query_params.get("redirect", "/")
    stok = request.query_params.get("token")
    nowfn = get_now_fn(request)
    try:
        auth_token = decode_auth_token(stok, nowfn=nowfn)
    except jwt.exceptions.PyJWTError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TimeException as e:
        user = await models.User.get_by_id(request.state.db, int(e.user_id))
        forward = request.query_params.get("redirect", "/")
        if user and user.email:
            try:
                await login_magic(
                    schemas.MagicLoginRequest(email=user.email, forward=forward),
                    request,
                )
            except HTTPException as e:
                # login_magic will throw a 403 if the user needs to use SSO
                # to log in. In that case, we redirect them to the SSO login
                # page.
                if e.status_code == 403:
                    return RedirectResponse(e.detail, status_code=303)
                else:
                    return RedirectResponse(
                        f"/login?expired=true&forward={forward}", status_code=303
                    )
            return RedirectResponse("/login?new_link=true", status_code=303)
        return RedirectResponse(
            f"/login?expired=true&forward={forward}", status_code=303
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    user = await models.User.get_by_id(request.state.db, int(auth_token.sub))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Figure out the appropriate continuation based on the user's authn method.
    # Currently we do find the authn method by checking the email domain against
    # our config, but in the future we might need to store this explicitly by user
    # in the database.
    login_config = authn_method_for_email(config.auth.authn_methods, user.email)

    if login_config.method == "sso":
        sso_path = f"/api/v1/login/sso?provider={login_config.provider}&redirect={dest.replace('#', '%23')}"
        return RedirectResponse(
            config.url(sso_path),
            status_code=303,
        )
    elif login_config.method == "magic_link":
        return redirect_with_session(dest, int(auth_token.sub), nowfn=nowfn)
    else:
        raise HTTPException(
            status_code=501, detail=f"Login method {login_config.method} not supported"
        )


@v1.get(
    "/api_keys/default",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.DefaultAPIKeys,
)
async def list_default_api_keys(request: Request):
    default_api_keys = await models.APIKey.get_all_default_keys(request.state.db)
    return schemas.DefaultAPIKeys(
        default_keys=[
            schemas.DefaultAPIKey(
                id=key.id,
                redacted_key=f"{key.api_key[:8]}{'*' * 10}{key.api_key[-4:]}",
                name=key.name,
                provider=key.provider,
                endpoint=key.endpoint,
            )
            for key in default_api_keys
        ]
    )


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

    user = await models.User.get_by_id(request.state.db, request.state.session.user.id)

    # Create an entry for the creator as the owner
    ucr = models.UserClassRole(
        user_id=request.state.session.user.id,
        class_id=new_class.id,
        subscribed_to_summaries=not user.dna_as_create,
    )
    request.state.db.add(ucr)

    grants = [
        (f"institution:{institution_id}", "parent", f"class:{new_class.id}"),
        (f"user:{request.state.session.user.id}", "teacher", f"class:{new_class.id}"),
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
                f"class:{new_class.id}#supervisor",
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
    "/stats",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.StatisticsResponse,
)
async def get_stats(request: Request):
    statistics = await get_statistics(request.state.db)
    return schemas.StatisticsResponse(statistics=statistics)


@v1.get(
    "/stats/models",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.ModelStatisticsResponse,
)
async def get_models_stats(request: Request):
    counts = await models.Assistant.get_count_by_model(request.state.db)
    stats = [{"model": k, "assistant_count": v} for (k, v) in counts]
    return schemas.ModelStatisticsResponse(statistics=stats)


@v1.get(
    "/stats/models/{model_name}/assistants",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.AssistantModelInfoResponse,
)
async def get_model_assistants(model_name: str, request: Request):
    assistants = await models.Assistant.get_by_model_with_stats(
        request.state.db, model_name
    )
    stats = [
        {
            "assistant_id": a.id,
            "assistant_name": a.name,
            "class_id": a.class_id,
            "class_name": a.class_name,
            "last_edited": a.updated or a.created,
            "last_user_activity": a.last_activity,
        }
        for a in assistants
    ]
    return schemas.AssistantModelInfoResponse(assistants=stats, model=model_name)


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
    class_ = await models.Class.get_by_id(request.state.db, int(class_id))
    class_.download_link_expiration = convert_seconds(
        config.artifact_store.download_link_expiration
    )
    return class_


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
    try:
        cls = await models.Class.update(request.state.db, int(class_id), update)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    supervisor_as_can_manage_assistants = (
        f"class:{class_id}#supervisor",
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
        revokes.append(supervisor_as_can_manage_assistants)
    else:
        grants.append(supervisor_as_can_manage_threads)
        grants.append(supervisor_as_can_manage_assistants)

    await request.state.authz.write_safe(grant=grants, revoke=revokes)

    return cls


@v1.delete(
    "/class/{class_id}",
    dependencies=[Depends(Authz("can_delete", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_class(class_id: str, request: Request):
    class_ = await models.Class.get_by_id(request.state.db, int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Group not found")

    if class_.api_key or class_.api_key_id:
        openai_client = await get_openai_client_for_class(request)
        # Delete all threads
        async for thread in models.Thread.get_ids_by_class_id(
            request.state.db, class_.id
        ):
            await delete_thread(class_id, str(thread.id), request, openai_client)

        # Delete all class assistants
        async for assistant_id in models.Assistant.async_get_by_class_id(
            request.state.db, class_.id
        ):
            await delete_assistant(class_id, str(assistant_id), request, openai_client)

        # Double check that we deleted all vector stores
        async for vector_store_id in models.VectorStore.get_id_by_class_id(
            request.state.db, class_.id
        ):
            await delete_vector_store(request.state.db, openai_client, vector_store_id)

    # All private and class files associated with the class_id
    # are deleted by the database cascade
    if class_.lms_status and class_.lms_status != schemas.LMSStatus.NONE:
        await remove_canvas_connection(request.state.db, class_.id, request=request)

    stmt = delete(models.UserClassRole).where(
        models.UserClassRole.class_id == class_.id
    )
    await request.state.db.execute(stmt)

    await class_.delete(request.state.db)
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/canvas/{tenant}/link",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.CanvasRedirect,
)
async def get_canvas_link(class_id: str, tenant: str, request: Request):
    canvas_settings = get_canvas_config(tenant)
    async with LightweightCanvasClient(
        canvas_settings,
        int(class_id),
        request,
    ) as client:
        return {"url": client.get_oauth_link()}


@v1.post(
    "/class/{class_id}/canvas/{tenant}/sync/dismiss",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def dismiss_canvas_sync(class_id: str, request: Request):
    await models.Class.dismiss_lms_sync(request.state.db, int(class_id))
    return {"status": "ok"}


@v1.post(
    "/class/{class_id}/canvas/{tenant}/sync/enable",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def enable_canvas_sync(class_id: str, request: Request):
    await models.Class.enable_lms_sync(request.state.db, int(class_id))
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/canvas/{tenant}/classes",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.LMSClasses,
)
async def get_canvas_classes(class_id: str, tenant: str, request: Request):
    canvas_settings = get_canvas_config(tenant)
    async with LightweightCanvasClient(
        canvas_settings,
        int(class_id),
        request,
    ) as client:
        try:
            courses = await client.get_courses()
            return {"classes": courses}
        except ClientResponseError as e:
            # If we get a 4xx error, mark the class as having a sync error before raising the error.
            # This will prompt the user to re-connect to Canvas before we sync again.
            # Otherwise, just display an error message.
            if e.code == 401:
                await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception("get_canvas_classes: ClientResponseError occurred")
            raise HTTPException(
                status_code=e.code, detail="Canvas returned an error: " + e.message
            ) from e
        except CanvasInvalidTokenException:
            await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception("get_canvas_classes: CanvasInvalidTokenException occurred")
            raise HTTPException(
                status_code=401,
                detail="Your Canvas token is invalid. Please reconnect to Canvas. If the problem persists, please contact us.",
            )
        except CanvasException as e:
            logger.exception("get_canvas_classes: CanvasException occurred")
            raise HTTPException(
                status_code=e.code or 500,
                detail=e.detail
                or "We faced an error while getting your Canvas classes.",
            ) from e
        except CanvasWarning as e:
            logger.warning("get_canvas_classes: CanvasWarning occurred: %s", e.detail)
            raise HTTPException(
                status_code=e.code or 500,
                detail=e.detail
                or "We faced an error while getting your Canvas classes.",
            ) from e
        except Exception as e:
            logger.exception("get_canvas_classes: Exception occurred")
            raise HTTPException(
                status_code=500,
                detail="We faced an internal error while getting your Canvas classes.",
            ) from e


@v1.post(
    "/class/{class_id}/canvas/{tenant}/classes/{canvas_class_id}/verify",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def verify_canvas_class_permissions(
    class_id: str, tenant: str, canvas_class_id: str, request: Request
):
    canvas_settings = get_canvas_config(tenant)
    async with LightweightCanvasClient(
        canvas_settings,
        int(class_id),
        request,
    ) as client:
        try:
            await client.verify_access(canvas_class_id)
            return {"status": "ok"}
        except CanvasException as e:
            logger.exception(
                "verify_canvas_class_permissions: CanvasException occurred"
            )
            raise HTTPException(
                status_code=e.code or 500,
                detail=e.detail
                or "We faced an error while verifying your access to this Canvas class.",
            )
        except CanvasAccessException as e:
            logger.warning(
                "verify_canvas_class_permissions: CanvasAccessException occurred: %s",
                e.detail,
            )
            raise HTTPException(
                status_code=e.code or 403,
                detail=e.detail
                or "We faced an error while getting your Canvas classes.",
            ) from e
        except CanvasWarning as e:
            logger.warning(
                "verify_canvas_class_permissions: CanvasWarning occurred: %s", e.detail
            )
            raise HTTPException(
                status_code=e.code or 500,
                detail=e.detail
                or "We faced an error while verifying your access to this Canvas class.",
            ) from e
        except ClientResponseError as e:
            # If we get a 401 error, mark the class as having a sync error.
            # Otherwise, just display an error message.
            if e.code == 401:
                await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception(
                "verify_canvas_class_permissions: ClientResponseError occurred"
            )
            raise HTTPException(
                status_code=e.code, detail="Canvas returned an error: " + e.message
            )
        except CanvasInvalidTokenException:
            await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception(
                "verify_canvas_class_permissions: CanvasInvalidTokenException occurred"
            )
            raise HTTPException(
                status_code=401,
                detail="Your Canvas token is invalid. Please reconnect to Canvas. If the problem persists, please contact us.",
            )
        except Exception:
            logger.exception("verify_canvas_class_permissions: Exception occurred")
            raise HTTPException(
                status_code=500,
                detail="We faced an internal error while verifying your access to this Canvas class.",
            )


@v1.post(
    "/class/{class_id}/canvas/{tenant}/classes/{canvas_class_id}",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def update_canvas_class(
    class_id: str, tenant: str, canvas_class_id: str, request: Request
):
    canvas_settings = get_canvas_config(tenant)
    async with LightweightCanvasClient(
        canvas_settings,
        int(class_id),
        request,
    ) as client:
        try:
            await client.set_canvas_class(canvas_class_id)
            return {"status": "ok"}
        except CanvasException as e:
            logger.exception("update_canvas_class: CanvasException occurred")
            raise HTTPException(
                status_code=e.code or 500,
                detail=e.detail or "We faced an error while setting your Canvas class.",
            )
        except CanvasAccessException as e:
            logger.warning(
                "update_canvas_class: CanvasAccessException occurred: %s", e.detail
            )
            raise HTTPException(
                status_code=e.code or 403,
                detail=e.detail
                or "We faced an error while getting your Canvas classes.",
            ) from e
        except CanvasWarning as e:
            logger.warning("update_canvas_class: CanvasWarning occurred: %s", e.detail)
            raise HTTPException(
                status_code=e.code or 500,
                detail=e.detail or "We faced an error while setting your Canvas class.",
            ) from e
        except ClientResponseError as e:
            # If we get a 401 error, mark the class as having a sync error.
            # Otherwise, just display an error message.
            if e.code == 401:
                await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception("update_canvas_class: ClientResponseError occurred")
            raise HTTPException(
                status_code=e.code, detail="Canvas returned an error: " + e.message
            )
        except CanvasInvalidTokenException:
            await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception("sync_canvas_class: CanvasInvalidTokenException occurred")
            raise HTTPException(
                status_code=401,
                detail="Your Canvas token is invalid. Please reconnect to Canvas. If the problem persists, please contact us.",
            )
        except Exception:
            logger.exception("update_canvas_class: Exception occurred")
            raise HTTPException(
                status_code=500,
                detail="We faced an internal error while setting your Canvas class.",
            )


@v1.post(
    "/class/{class_id}/canvas/{tenant}/sync",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def sync_canvas_class(
    class_id: str, tenant: str, request: Request, tasks: BackgroundTasks
):
    canvas_settings = get_canvas_config(tenant)
    async with ManualCanvasClient(
        canvas_settings,
        int(class_id),
        request,
        tasks,
    ) as client:
        try:
            await client.sync_roster()
            return {"status": "ok"}
        except ClientResponseError as e:
            # If we get a 401 error, mark the class as having a sync error.
            # Otherwise, just display an error message.
            if e.code == 401:
                await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception("sync_canvas_class: ClientResponseError occurred")
            raise HTTPException(
                status_code=e.code, detail="Canvas returned an error: " + e.message
            )
        except (CanvasException, AddUserException) as e:
            if e.code == 403:
                await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception(
                "sync_canvas_class: CanvasException or AddUserException occurred"
            )
            raise HTTPException(
                status_code=e.code or 500,
                detail=e.detail or "We faced an error while syncing with Canvas.",
            )
        except CanvasWarning as e:
            logger.warning("sync_canvas_class: CanvasWarning occurred: %s", e.detail)
            raise HTTPException(
                status_code=e.code or 500,
                detail=e.detail or "We faced an error while syncing with Canvas.",
            )
        except CanvasInvalidTokenException:
            await models.Class.mark_lms_sync_error(request.state.db, int(class_id))
            logger.exception("sync_canvas_class: CanvasInvalidTokenException occurred")
            raise HTTPException(
                status_code=401,
                detail="Your Canvas token is invalid. Please reconnect to Canvas. If the problem persists, please contact us.",
            )
        except Exception:
            logger.exception("sync_canvas_class: Exception occurred")
            raise HTTPException(
                status_code=500,
                detail="We faced an internal error while syncing with Canvas.",
            )


@v1.delete(
    "/class/{class_id}/canvas/{tenant}/sync",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def unlink_canvas_class(
    class_id: str, tenant: str, request: Request, keep_users: bool = True
):
    canvas_settings = get_canvas_config(tenant)
    userIds = await models.Class.remove_lms_sync(
        request.state.db,
        int(class_id),
        canvas_settings.tenant,
        schemas.LMSType(canvas_settings.type),
        keep_users=keep_users,
    )
    await delete_canvas_permissions(request.state.authz, userIds, class_id)
    logger.info(
        f"Canvas class unlinked from PingPong class {class_id} by user {request.state.session.user.id}."
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/canvas/{tenant}/account",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def remove_canvas_connection(
    class_id: str,
    tenant: str,
    request: Request,
    keep_users: bool = True,
):
    canvas_settings = get_canvas_config(tenant)
    async with LightweightCanvasClient(
        canvas_settings, int(class_id), request
    ) as client:
        try:
            await client.log_out()
        except ClientResponseError as e:
            logger.exception("delete_canvas_permissions: ClientResponseError occurred")
            raise HTTPException(
                status_code=e.code,
                detail="Canvas returned an error when removing your account: "
                + e.message,
            )
        except CanvasInvalidTokenException:
            logger.warning(
                "delete_canvas_permissions: CanvasInvalidTokenException occurred",
                exc_info=True,
            )
        except CanvasException as e:
            logger.exception("delete_canvas_permissions: CanvasException occurred")
            raise HTTPException(
                status_code=e.code or 500,
                detail="We faced an error while removing your account: " + e.detail,
            )
        except Exception:
            logger.exception("delete_canvas_permissions: Exception occurred")
            raise HTTPException(
                status_code=500,
                detail="We faced an internal error while removing your account.",
            )

        try:
            userIds = await models.Class.remove_lms_sync(
                request.state.db,
                int(class_id),
                canvas_settings.tenant,
                schemas.LMSType(canvas_settings.type),
                kill_connection=True,
                keep_users=keep_users,
            )
            await delete_canvas_permissions(request.state.authz, userIds, class_id)
            logger.info(
                f"Canvas account removed from PingPong class {class_id} by user {request.state.session.user.id}."
            )
        except Exception:
            logger.exception("remove_canvas_connection: Exception occurred")
            raise HTTPException(
                status_code=500,
                detail="We faced an internal error while removing your account.",
            )

    return {"status": "ok"}


@v1.post(
    "/class/{class_id}/summarize",
    dependencies=[Depends(Authz("can_receive_summaries", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def request_class_summary(
    class_id: str,
    request: Request,
    tasks: BackgroundTasks,
    openai_client: OpenAIClient,
    opts: schemas.ActivitySummaryOpts,
):
    class_ = await models.Class.get_by_id(request.state.db, int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Group not found")
    if class_.private:
        raise HTTPException(
            status_code=403,
            detail="Cannot create assistant summaries for a private class",
        )
    user = await models.User.get_by_id(request.state.db, request.state.session.user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Calculate date X days ago
    after = utcnow() - timedelta(days=opts.days or 7)

    tasks.add_task(
        safe_task,
        send_class_summary_to_user_task,
        openai_client,
        int(class_id),
        user.id,
        after,
        summarize_even_if_no_threads=True,
    )
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/summarize/subscription",
    dependencies=[Depends(Authz("can_receive_summaries", "class:{class_id}"))],
    response_model=schemas.SummarySubscriptionResult,
)
async def get_class_summary_subscription(class_id: str, request: Request):
    subscribed = await models.UserClassRole.is_subscribed_to_summaries(
        request.state.db, request.state.session.user.id, int(class_id)
    )
    return {"subscribed": subscribed}


@v1.post(
    "/class/{class_id}/summarize/subscription",
    dependencies=[Depends(Authz("can_receive_summaries", "class:{class_id}"))],
)
async def subscribe_to_class_summary(class_id: str, request: Request):
    class_ = await models.Class.get_by_id(request.state.db, int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Group not found")
    if class_.private:
        raise HTTPException(
            status_code=403,
            detail="Cannot subscribe to Activity Summaries for a private group.",
        )
    if not class_.api_key_id and not class_.api_key:
        raise HTTPException(
            status_code=403,
            detail="Cannot subscribe to Activity Summaries for a group with no billing information.",
        )
    await models.UserClassRole.subscribe_to_summaries(
        request.state.db, request.state.session.user.id, int(class_id)
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/summarize/subscription",
    dependencies=[Depends(Authz("can_receive_summaries", "class:{class_id}"))],
)
async def unsubscribe_from_class_summary(class_id: str, request: Request):
    class_ = await models.Class.get_by_id(request.state.db, int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Group not found")
    if class_.private:
        raise HTTPException(
            status_code=403,
            detail="Cannot subscribe to Activity Summaries for a private group.",
        )
    if not class_.api_key_id and not class_.api_key:
        raise HTTPException(
            status_code=403,
            detail="Cannot subscribe to Activity Summaries for a group with no billing information.",
        )
    await models.UserClassRole.unsubscribe_from_summaries(
        request.state.db, request.state.session.user.id, int(class_id)
    )
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/supervisors",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.ClassSupervisors,
)
async def list_class_supervisors(class_id: str, request: Request):
    supervisor_ids = await request.state.authz.list_entities(
        f"class:{class_id}",
        "supervisor",
        "user",
    )
    supervisors = await models.User.get_all_by_id_if_in_class(
        request.state.db, supervisor_ids, int(class_id)
    )
    supervisors_users = []
    for supervisor in supervisors:
        supervisors_users.append(
            schemas.SupervisorUser(
                name=(
                    supervisor.display_name
                    if supervisor.display_name
                    else " ".join(
                        filter(None, [supervisor.first_name, supervisor.last_name])
                    )
                    or None
                ),
                email=supervisor.email,
            )
        )
    return {"users": supervisors_users}


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
                lms_tenant=u.lms_tenant or None,
                lms_type=u.lms_type or None,
            )
        )

    return {"users": class_users, "limit": limit, "offset": offset, "total": total}


@v1.post(
    "/class/{class_id}/user/validate",
    dependencies=[Depends(Authz("can_manage_users", "class:{class_id}"))],
    response_model=schemas.EmailValidationResults,
)
async def validate_user_emails(
    class_id: str, data: schemas.EmailValidationRequest, request: Request
):
    return await validate_email_addresses(request.state.db, data.emails)


@v1.post(
    "/class/{class_id}/user/revalidate",
    dependencies=[Depends(Authz("can_manage_users", "class:{class_id}"))],
    response_model=schemas.EmailValidationResults,
)
async def revalidate_user_emails(
    class_id: str, data: schemas.EmailValidationResults, request: Request
):
    return await revalidate_email_addresses(request.state.db, data.results)


@v1.post(
    "/class/{class_id}/user",
    dependencies=[Depends(Authz("can_manage_users", "class:{class_id}"))],
    response_model=schemas.CreateUserResults,
)
async def add_users_to_class(
    class_id: str,
    new_ucr: schemas.CreateUserClassRoles,
    request: Request,
    tasks: BackgroundTasks,
):
    try:
        return await AddNewUsersManual(
            class_id, new_ucr, request, tasks
        ).add_new_users()
    except AddUserException as e:
        logger.exception("add_users_to_class: AddUserException occurred")
        raise HTTPException(
            status_code=e.code or 500,
            detail=e.detail or "We faced an error while adding users.",
        )


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

    try:
        await check_permissions(request, uid, cid)
    except CheckUserPermissionException as e:
        logger.exception(
            "update_user_class_role: CheckUserPermissionException occurred"
        )
        raise HTTPException(
            status_code=e.code or 500,
            detail=e.detail or "We faced an error while verifying your permissions.",
        )
    except Exception:
        logger.exception("update_user_class_role: Exception occurred")
        raise HTTPException(
            status_code=500,
            detail="We faced an internal error while verifying your permissions.",
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
    dependencies=[Depends(Authz("supervisor", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def remove_user_from_class(class_id: str, user_id: str, request: Request):
    cid = int(class_id)
    uid = int(user_id)

    try:
        await check_permissions(
            request,
            uid,
            cid,
        )
    except CheckUserPermissionException as e:
        logger.exception(
            "remove_user_from_class: CheckUserPermissionException occurred"
        )
        raise HTTPException(
            status_code=e.code or 500,
            detail=e.detail or "We faced an error while verifying your permissions.",
        )
    except Exception:
        logger.exception("remove_user_from_class: Exception occurred")
        raise HTTPException(
            status_code=500,
            detail="We faced an internal error while verifying your permissions.",
        )
    await models.UserClassRole.delete(request.state.db, uid, cid)

    revokes = list[Relation]()
    for role in ["admin", "teacher", "student"]:
        revokes.append((f"user:{uid}", role, f"class:{cid}"))

    await request.state.authz.write_safe(revoke=revokes)
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/api_key/check",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.APIKeyCheck,
)
async def check_class_api_key(class_id: str, request: Request):
    result = await models.Class.get_api_key(request.state.db, int(class_id))
    if result.api_key_obj:
        return {"has_api_key": True}
    elif result.api_key:
        return {"has_api_key": True}
    return {"has_api_key": False}


@v1.put(
    "/class/{class_id}/api_key",
    dependencies=[Depends(Authz("admin", "class:{class_id}"))],
    response_model=schemas.APIKeyResponse,
)
async def update_class_api_key(
    class_id: str, update: schemas.UpdateApiKey, request: Request
):
    if not update.api_key:
        raise HTTPException(
            status_code=400,
            detail="API key must be provided to update the class API key.",
        )
    existing_key = await models.Class.get_api_key(request.state.db, int(class_id))
    if (
        existing_key.api_key_obj
        and existing_key.api_key_obj.api_key == update.api_key
        and existing_key.api_key_obj.provider == update.provider
        and existing_key.api_key_obj.endpoint == update.endpoint
        and existing_key.api_key_obj.api_version == update.api_version
    ):
        return {"api_key": existing_key.api_key_obj}
    if existing_key.api_key == update.api_key:
        return {
            "api_key": schemas.ApiKey(api_key=existing_key.api_key, provider="openai")
        }
    elif not existing_key.api_key_obj and not existing_key.api_key:
        if not await validate_api_key(
            update.api_key,
            update.provider.value,
            update.endpoint,
            update.api_version,
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid API connection information provided. Please try again.",
            )
        api_key_obj = await models.Class.update_api_key(
            request.state.db,
            int(class_id),
            update.api_key,
            provider=update.provider,
            endpoint=update.endpoint if update.provider == "azure" else None,
            api_version=update.api_version if update.provider == "azure" else None,
            available_as_default=False,
        )
        await request.state.authz.write_safe(
            grant=[
                (
                    f"user:{request.state.session.user.id}",
                    "can_view_api_key",
                    f"class:{class_id}",
                )
            ]
        )
        return {"api_key": api_key_obj}
    else:
        raise HTTPException(
            status_code=400,
            detail="API key already exists. Delete it first to create a new one.",
        )


@v1.get(
    "/class/{class_id}/api_key",
    dependencies=[Depends(Authz("can_view_api_key", "class:{class_id}"))],
    response_model=schemas.APIKeyResponse,
)
async def get_class_api_key(class_id: str, request: Request):
    response = None
    result = await models.Class.get_api_key(request.state.db, int(class_id))
    if result.api_key_obj:
        api_key_obj = result.api_key_obj
        response = schemas.ApiKey(
            api_key=f"{api_key_obj.api_key[:8]}{'*' * 20}{api_key_obj.api_key[-4:]}",
            provider=api_key_obj.provider,
            endpoint=api_key_obj.endpoint,
            api_version=api_key_obj.api_version,
        )
    elif result.api_key:
        response = schemas.ApiKey(
            api_key=f"{result.api_key[:8]}{'*' * 20}{result.api_key[-4:]}",
            provider="openai",
        )

    return {"api_key": response}


@v1.get(
    "/class/{class_id}/models",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.AssistantModels,
)
async def list_class_models(
    class_id: str, request: Request, openai_client: OpenAIClient
):
    """List available models for the class assistants."""
    try:
        all_models = await openai_client.models.list()
    except openai.AuthenticationError as e:
        raise HTTPException(
            status_code=401,
            detail="We couldn't fetch your available models: "
            + get_details_from_api_error(
                e, "OpenAI was unable to authenticate your request."
            ),
        )
    except openai.APIError as e:
        raise HTTPException(
            status_code=500,
            detail="We couldn't fetch your available models: "
            + get_details_from_api_error(
                e, "OpenAI was unable to process your request."
            ),
        )
    known_models: dict[str, schemas.AssistantModelDict] = {
        # ----------------- Latest Models -----------------
        #
        # -----------------   o* Family   -----------------
        # Temporarily unavailable as it doesn't support streaming.
        # "o1": {
        #     "name": "o1",
        #     "sort_order": 3,
        #     "is_new": True,
        #     "highlight": False,
        #     "is_latest": True,
        #     "supports_vision": False,
        #     "supports_file_search": False,
        #     "supports_code_interpreter": False,
        #     "supports_temperature": False,
        #     "supports_reasoning": True,
        #     "description": "Reasoning model designed to solve hard problems across domains. Limited capabilities.",
        # },
        "o3-mini": {
            "name": "o3 mini",
            "sort_order": 2,
            "is_new": True,
            "highlight": False,
            "is_latest": True,
            "supports_vision": False,
            "supports_file_search": False,
            "supports_code_interpreter": False,
            "supports_temperature": False,
            "supports_reasoning": True,
            "description": "Faster reasoning model particularly good at coding, math, and science. Limited capabilities.",
        },
        #
        # -----------------   gpt-4o Family   -----------------
        #
        "gpt-4o": {
            "name": "GPT-4o",
            "sort_order": 0,
            "is_new": False,
            "highlight": True,
            "is_latest": True,
            "supports_vision": True,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "The latest GPT-4o model, suitable for complex, multi-step tasks.",
        },
        "gpt-4o-mini": {
            "name": "GPT-4o mini",
            "sort_order": 1,
            "is_new": False,
            "highlight": False,
            "is_latest": True,
            "supports_vision": True,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "The latest GPT-4o mini model, suitable for fast, lightweight tasks. More capable than GPT-3.5 Turbo.",
        },
        #
        # -----------------   gpt-4 Family   -----------------
        #
        "gpt-4-turbo": {
            "name": "GPT-4 Turbo",
            "sort_order": 4,
            "is_new": False,
            "highlight": False,
            "is_latest": True,
            "supports_vision": True,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "The latest GPT-4 Turbo model.",
        },
        "gpt-4-turbo-preview": {
            "name": "GPT-4 Turbo preview",
            "sort_order": 5,
            "is_new": False,
            "highlight": False,
            "is_latest": True,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "The latest GPT-4 Turbo preview model.",
        },
        #
        # -----------------   gpt-3.5 Family   -----------------
        #
        "gpt-3.5-turbo": {
            "name": "GPT-3.5 Turbo",
            "sort_order": 6,
            "is_new": False,
            "highlight": False,
            "is_latest": True,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "The latest GPT-3.5 Turbo model. Choose the more capable GPT-4o mini model instead.",
        },
        # gpt-3.5-turbo equivalent model in Azure
        "gpt-35-turbo": {
            "name": "GPT-3.5 Turbo",
            "sort_order": 6,
            "is_new": False,
            "highlight": False,
            "is_latest": True,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "The latest GPT-3.5 Turbo model. Choose the more capable GPT-4o mini model instead.",
        },
        #
        # ----------------- Pinned Models -----------------
        #
        # -----------------   o* Family   -----------------
        "o3-mini-2025-01-31": {
            "name": "o3-mini-2025-01-31",
            "sort_order": 8,
            "is_new": True,
            "highlight": False,
            "is_latest": False,
            "supports_vision": False,
            "supports_file_search": False,
            "supports_code_interpreter": False,
            "supports_temperature": False,
            "supports_reasoning": True,
            "description": "o3 mini initial release version. Limited capabilities.",
        },
        # Temporarily unavailable as it doesn't support streaming.
        # "o1-2024-12-17": {
        #     "name": "o1-2024-12-17",
        #     "sort_order": 9,
        #     "is_new": True,
        #     "highlight": False,
        #     "is_latest": False,
        #     "supports_vision": False,
        #     "supports_file_search": False,
        #     "supports_code_interpreter": False,
        #     "supports_temperature": False,
        #     "supports_reasoning": True,
        #     "description": "o1 initial release version. Limited capabilities.",
        # },
        # -----------------   gpt-4o Family   -----------------
        "gpt-4o-2024-11-20": {
            "name": "gpt-4o-2024-11-20",
            "sort_order": 11,
            "is_latest": False,
            "is_new": True,
            "highlight": False,
            "supports_vision": True,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "New GPT-4o model snapshot with enhanced creative writing ability.",
        },
        "gpt-4o-2024-08-06": {
            "name": "gpt-4o-2024-08-06",
            "sort_order": 13,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": True,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-4o model snapshot. GPT-4o (Latest) points to this version.",
        },
        "gpt-4o-2024-05-13": {
            "name": "gpt-4o-2024-05-13",
            "sort_order": 14,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": True,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-4o initial release version, 2x faster than GPT-4 Turbo.",
        },
        "gpt-4o-mini-2024-07-18": {
            "name": "gpt-4o-mini-2024-07-18",
            "sort_order": 10,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": True,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-4o mini initial release version.",
        },
        # -----------------   gpt-4 Family   -----------------
        "gpt-4-turbo-2024-04-09": {
            "name": "gpt-4-turbo-2024-04-09",
            "sort_order": 15,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": True,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-4 Turbo with Vision model.",
        },
        "gpt-4-0125-preview": {
            "name": "gpt-4-0125-preview",
            "sort_order": 16,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": 'GPT-4 Turbo preview model with a fix for "laziness," where the model doesn\'t complete a task.',
        },
        # Azure model equivalent
        "gpt-4-0125-Preview": {
            "name": "gpt-4-0125-Preview",
            "sort_order": 16,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": 'GPT-4 Turbo preview model with a fix for "laziness," where the model doesn\'t complete a task.',
        },
        "gpt-4-1106-preview": {
            "name": "gpt-4-1106-preview",
            "sort_order": 17,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-4 Turbo preview model with improved instruction following, reproducible outputs, and more.",
        },
        # Azure model equivalent
        "gpt-4-1106-Preview": {
            "name": "gpt-4-1106-Preview",
            "sort_order": 17,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-4 Turbo preview model with improved instruction following, reproducible outputs, and more.",
        },
        # -----------------   gpt-3.5 Family   -----------------
        "gpt-3.5-turbo-0125": {
            "name": "gpt-3.5-turbo-0125",
            "sort_order": 18,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-3.5 Turbo model with higher accuracy at responding in requested formats.",
        },
        # Azure model equivalent
        "gpt-35-turbo-0125": {
            "name": "gpt-35-turbo-0125",
            "sort_order": 18,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-3.5 Turbo model with higher accuracy at responding in requested formats.",
        },
        "gpt-3.5-turbo-1106": {
            "name": "gpt-3.5-turbo-1106",
            "sort_order": 19,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-3.5 Turbo model with improved instruction following, reproducible outputs, and more.",
        },
        # Azure model equivalent
        "gpt-35-turbo-1106": {
            "name": "gpt-35-turbo-1106",
            "sort_order": 19,
            "is_latest": False,
            "is_new": False,
            "highlight": False,
            "supports_vision": False,
            "supports_file_search": True,
            "supports_code_interpreter": True,
            "supports_temperature": True,
            "supports_reasoning": False,
            "description": "GPT-3.5 Turbo model with improved instruction following, reproducible outputs, and more.",
        },
    }
    filtered = [
        {
            "id": m.id,
            "created": datetime.fromtimestamp(m.created or m.created_at or 0),
            "owner": m.owned_by or "",
            "name": known_models[m.id]["name"],
            "sort_order": known_models[m.id]["sort_order"],
            "description": known_models[m.id]["description"],
            "is_latest": known_models[m.id]["is_latest"],
            "is_new": known_models[m.id]["is_new"],
            "highlight": known_models[m.id]["highlight"],
            "supports_vision": known_models[m.id]["supports_vision"],
            "supports_file_search": known_models[m.id]["supports_file_search"],
            "supports_code_interpreter": known_models[m.id][
                "supports_code_interpreter"
            ],
            "supports_temperature": known_models[m.id]["supports_temperature"],
            "supports_reasoning": known_models[m.id]["supports_reasoning"],
        }
        for m in all_models.data
        if m.id in known_models.keys()
    ]
    if isinstance(openai_client, openai.AsyncAzureOpenAI) and any(
        m.id == "gpt-4-turbo-2024-04-09" for m in all_models.data
    ):
        filtered.append(
            {
                "id": "gpt-4-turbo",
                "created": 0,
                "owner": "",
                "name": "GPT-4 Turbo",
                "sort_order": 4,
                "is_new": False,
                "highlight": False,
                "is_latest": True,
                "supports_vision": True,
                "supports_file_search": True,
                "supports_code_interpreter": True,
                "supports_temperature": True,
                "supports_reasoning": False,
                "description": "The latest GPT-4 Turbo model.",
            }
        )
    if isinstance(openai_client, openai.AsyncAzureOpenAI) and any(
        m.id == "gpt-4-0125-Preview" for m in all_models.data
    ):
        filtered.append(
            {
                "id": "gpt-4-turbo-preview",
                "created": 0,
                "owner": "",
                "name": "GPT-4 Turbo preview",
                "sort_order": 5,
                "is_new": False,
                "highlight": False,
                "is_latest": True,
                "supports_vision": False,
                "supports_file_search": True,
                "supports_code_interpreter": True,
                "supports_temperature": True,
                "supports_reasoning": False,
                "description": "The latest GPT-4 Turbo preview model.",
            }
        )

    AZURE_UNAVAILABLE_MODELS = [
        "gpt-4o-2024-11-20",
        "o1-2024-12-17",
        "o3-mini",
        "o3-mini-2025-01-31",
    ]

    if isinstance(openai_client, openai.AsyncAzureOpenAI):
        filtered = [m for m in filtered if m["id"] not in AZURE_UNAVAILABLE_MODELS]

    # Vision is not supported in Azure, set vision_support_override to False
    if isinstance(openai_client, openai.AsyncAzureOpenAI):
        for model in filtered:
            model["vision_support_override"] = (
                False if model["supports_vision"] else None
            )

    filtered.sort(key=lambda x: x["sort_order"])

    return {
        "models": filtered,
    }


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
    messages, [assistant, file_names, all_files], runs_result = await asyncio.gather(
        openai_client.beta.threads.messages.list(
            thread.thread_id, limit=20, order="desc"
        ),
        models.Thread.get_thread_components(request.state.db, thread.id),
        openai_client.beta.threads.runs.list(thread.thread_id, limit=1, order="desc"),
    )
    last_run = [r async for r in runs_result]
    current_user_ids = [
        request.state.session.user.id
    ] + await models.User.get_previous_ids_by_id(
        request.state.db, request.state.session.user.id
    )
    if messages.data:
        users = {str(u.id): u for u in thread.users}

    for message in messages.data:
        for content in message.content:
            if content.type == "text" and content.text.annotations:
                for annotation in content.text.annotations:
                    if annotation.type == "file_citation" and annotation.file_citation:
                        annotation.file_citation.file_name = file_names.get(
                            annotation.file_citation.file_id, "Unknown citation"
                        )
        user_id = message.metadata.pop("user_id", None)
        if not user_id:
            continue
        message.metadata["is_current_user"] = int(user_id) in current_user_ids
        message.metadata["name"] = (
            "Anonymous User" if thread.private else pseudonym(thread, users[user_id])
        )
    placeholder_ci_calls = []
    if "code_interpreter" in thread.tools_available:
        placeholder_ci_calls = await get_placeholder_ci_calls(
            request.state.db,
            messages.data[0].assistant_id if messages.data[0].assistant_id else "None",
            thread.thread_id,
            thread.id,
            messages.data[-1].created_at,
        )

    if assistant:
        thread.assistant_names = {assistant.id: assistant.name}
    else:
        thread.assistant_names = {0: "Deleted Assistant"}
    thread.user_names = user_names(thread, request.state.session.user.id)

    return {
        "thread": thread,
        "model": assistant.model if assistant else "None",
        "tools_available": thread.tools_available,
        "run": last_run[0] if last_run else None,
        "messages": list(messages.data),
        "limit": 20,
        "ci_messages": placeholder_ci_calls,
        "attachments": all_files,
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
    "/class/{class_id}/export",
    dependencies=[Depends(Authz("supervisor", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def export_class_threads(
    class_id: str, request: Request, tasks: BackgroundTasks, openai_client: OpenAIClient
):
    class_ = await models.Class.get_by_id(request.state.db, int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Class not found")
    if class_.private:
        raise HTTPException(
            status_code=403,
            detail="Cannot export private classes",
        )
    tasks.add_task(
        safe_task,
        export_class_threads_anonymized,
        openai_client,
        class_id,
        request.state.session.user.id,
    )
    return {"status": "ok"}


@v1.post(
    "/admin/migrate/assistants/model",
    dependencies=[Depends(Authz("admin"))],
)
async def migrate_models(
    req: schemas.AssistantModelUpgradeRequest, request: Request, tasks: BackgroundTasks
):
    tasks.add_task(
        safe_task, upgrade_assistants_model, req.deprecated_model, req.replacement_model
    )
    return {"status": "ok"}


@v1.get(
    "/admin/export/threads",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def export_class_threads_multiple_classes(
    data: schemas.MultipleClassThreadExportRequest,
    request: Request,
    tasks: BackgroundTasks,
):
    tasks.add_task(
        safe_task,
        export_threads_multiple_classes,
        data.class_ids,
        request.state.session.user.id,
        False,
        data.user_ids,
        data.user_emails,
    )
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/export/download",
    dependencies=[Depends(Authz("supervisor", "class:{class_id}"))],
)
async def redirect_to_export(class_id: str, request: Request):
    token = request.query_params.get("token")
    nowfn = get_now_fn(request)
    try:
        auth_token = decode_auth_token(token, nowfn=nowfn)
        sub_data = json.loads(auth_token.sub)
        requestor_user_id = sub_data["user_id"]
        download_name = sub_data["download_name"]
        if requestor_user_id != request.state.session.user.id:
            return RedirectResponse(
                config.url(f"/group/{class_id}/manage?error_code=8"),
                status_code=303,
            )
        return StreamingResponse(
            config.artifact_store.store.get(download_name),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={download_name}"},
        )
    except TimeException:
        return RedirectResponse(
            config.url(f"/group/{class_id}/manage?error_code=7"),
            status_code=303,
        )
    except (jwt.exceptions.PyJWTError, Exception):
        return RedirectResponse(
            config.url(f"/group/{class_id}/manage?error_code=6"),
            status_code=303,
        )
    except ArtifactStoreError:
        return RedirectResponse(
            config.url(f"/group/{class_id}/manage?error_code=9"),
            status_code=303,
        )


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
    file_names = await models.Thread.get_file_search_files(request.state.db, thread.id)

    if messages.data:
        users = {u.id: u.created for u in thread.users}

    for message in messages.data:
        for content in message.content:
            if content.type == "text" and content.text.annotations:
                for annotation in content.text.annotations:
                    if annotation.type == "file_citation" and annotation.file_citation:
                        annotation.file_citation.file_name = file_names.get(
                            annotation.file_citation.file_id, "Unknown citation"
                        )
        user_id = message.metadata.pop("user_id", None)
        if not user_id:
            continue
        message.metadata["is_current_user"] = user_id == str(
            request.state.session.user.id
        )
        message.metadata["name"] = (
            "Anonymous User" if thread.private else pseudonym(thread, users[user_id])
        )

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
    while last_run.status not in {
        "completed",
        "failed",
        "incomplete",
        "expired",
        "cancelled",
    }:
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
            logger.exception("Error connecting to OpenAI: %s", e)
            # Continue polling

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
        "can_participate",
        "thread",
    )
    threads = await models.Thread.get_n_by_id(
        request.state.db,
        thread_ids,
        limit,
        before=current_latest_time,
    )

    return {"threads": process_threads(threads, request.state.session.user.id)}


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

    # Normally we expect users either to be able to see a small number of threads.
    # A few users have access to a large number of threads. Currently, these two
    # cases require different query strategies.
    #
    # For low cardinality users, we can query the set of threads they can see from
    # the authz server and then pull them from the database.
    #
    # For high cardinality users, it's much faster to pull all threads from the database
    # and filter out the relative few they can't see.
    expect_high_cardinality = await request.state.authz.test(
        f"user:{request.state.session.user.id}",
        "admin",
        request.state.authz.root,
    )

    if expect_high_cardinality:
        logger.info("Using high-cardinality strategy for all_threads query")

        async def _batch_check_can_view(
            threads: list[models.Thread],
        ) -> list[models.Thread]:
            allows = await request.state.authz.check(
                [
                    (
                        f"user:{request.state.session.user.id}",
                        "can_view",
                        f"thread:{t.id}",
                    )
                    for t in threads
                ]
            )
            return [t for t, allow in zip(threads, allows) if allow]

        threads = await models.Thread.get_n(
            request.state.db,
            n=limit,
            before=current_latest_time,
            class_id=class_id,
            private=private,
            filter_batch=_batch_check_can_view,
        )
    else:
        logger.info("Using low-cardinality strategy for all_threads query")
        thread_ids = await request.state.authz.list(
            f"user:{request.state.session.user.id}",
            "can_view",
            "thread",
        )
        logger.info("/threads: FGA Returned %s thread_ids", len(thread_ids))
        threads = await models.Thread.get_n_by_id(
            request.state.db,
            thread_ids,
            limit,
            before=current_latest_time,
            private=private,
            class_id=class_id,
        )

    return {"threads": process_threads(threads, request.state.session.user.id)}


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
        thread_ids,
        limit,
        before=current_latest_time,
    )

    return {"threads": process_threads(threads, request.state.session.user.id)}


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
    vector_store_id = None
    vector_store_object_id = None
    tool_resources: ToolResources = {}

    if req.file_search_file_ids:
        vector_store_id, vector_store_object_id = await create_vector_store(
            request.state.db,
            openai_client,
            class_id,
            req.file_search_file_ids,
            type=schemas.VectorStoreType.THREAD,
            upload_to_oai=False,
        )
        tool_resources["file_search"] = {"vector_store_ids": [vector_store_id]}

    vision_image_descriptions = None
    if req.vision_image_descriptions:
        vision_image_descriptions = generate_vision_image_descriptions_string(
            req.vision_image_descriptions
        )
    messageContent: MessageContentPartParam = [
        {
            "type": "text",
            "text": req.message + (vision_image_descriptions or ""),
        }
    ]

    attachments: list[Attachment] = []
    attachments_dict: dict[str, list[dict[str, str]]] = {}

    if req.file_search_file_ids:
        for file_id in req.file_search_file_ids:
            attachments_dict.setdefault(file_id, []).append({"type": "file_search"})

    if req.code_interpreter_file_ids:
        for file_id in req.code_interpreter_file_ids:
            attachments_dict.setdefault(file_id, []).append(
                {"type": "code_interpreter"}
            )

    for file_id, tools in attachments_dict.items():
        attachments.append({"file_id": file_id, "tools": tools})

    if req.vision_file_ids:
        [
            messageContent.append({"type": "image_file", "image_file": {"file_id": id}})
            for id in req.vision_file_ids
        ]
    thread = None
    try:
        thread, parties, thread_name = await asyncio.gather(
            openai_client.beta.threads.create(
                messages=[
                    {
                        "metadata": {"user_id": str(request.state.session.user.id)},
                        "role": "user",
                        "content": messageContent,
                        "attachments": attachments,
                    }
                ],
                tool_resources=tool_resources,
            ),
            models.User.get_all_by_id(request.state.db, req.parties),
            get_initial_thread_conversation_name(
                openai_client,
                request.state.db,
                req.message,
                req.vision_file_ids,
                class_id,
            ),
        )
    except openai.InternalServerError:
        logger.exception("Error creating thread")
        if vector_store_id:
            await openai_client.beta.vector_stores.delete(vector_store_id)
        if thread:
            await openai_client.beta.threads.delete(thread.id)
        raise HTTPException(
            status_code=503,
            detail="OpenAI is experiencing issues so we can't create your conversation right now. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
        )
    except (openai.APIError, Exception):
        logger.exception("Error creating thread")
        if vector_store_id:
            await openai_client.beta.vector_stores.delete(vector_store_id)
        if thread:
            await openai_client.beta.threads.delete(thread.id)
        raise HTTPException(
            status_code=400,
            detail="Something went wrong while creating your conversation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
        )

    tools_export = req.model_dump(include={"tools_available"})

    if not thread:
        if vector_store_id:
            await openai_client.beta.vector_stores.delete(vector_store_id)
        raise HTTPException(
            status_code=500,
            detail="We faced an error while creating your conversation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
        )
    new_thread = {
        "name": thread_name,
        "class_id": int(class_id),
        "private": True if parties else False,
        "users": parties or [],
        "thread_id": thread.id,
        "assistant_id": req.assistant_id,
        "vector_store_id": vector_store_object_id,
        "code_interpreter_file_ids": req.code_interpreter_file_ids or [],
        "image_file_ids": req.vision_file_ids or [],
        "tools_available": json.dumps(tools_export["tools_available"] or []),
        "version": 2,
        "last_activity": func.now(),
    }

    result: None | models.Thread = None
    try:
        result = await models.Thread.create(request.state.db, new_thread)

        grants = [
            (f"class:{class_id}", "parent", f"thread:{result.id}"),
        ] + [(f"user:{p.id}", "party", f"thread:{result.id}") for p in parties]
        await request.state.authz.write(grant=grants)

        return result
    except Exception as e:
        logger.exception("Error creating thread: %s", e)
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
    try:
        thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
        asst = await models.Assistant.get_by_id(request.state.db, thread.assistant_id)
        file_names = await models.Thread.get_file_search_files(
            request.state.db, thread.id
        )
        vector_store_id = (
            await models.VectorStore.get_vector_store_id_by_id(
                request.state.db, thread.vector_store_id
            )
            if thread.vector_store_id
            else None
        )
        stream = run_thread(
            openai_client,
            class_id=class_id,
            thread_id=thread.thread_id,
            assistant_id=asst.assistant_id,
            message=[],
            file_names=file_names,
            vector_store_id=vector_store_id,
        )
    except Exception as e:
        logger.exception("Error running thread")
        raise HTTPException(
            status_code=500,
            detail="We faced an error while sending your message. " + str(e),
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
    tool_resources: ToolResources = {}

    # Check that assistant exists
    if not thread.assistant_id:
        raise HTTPException(
            status_code=404,
            detail="The assistant for this thread no longer exists.",
        )

    # Check user has permission to view this assistant
    if not (
        await request.state.authz.check(
            [
                (
                    f"user:{request.state.session.user.id}",
                    "can_view",
                    f"assistant:{thread.assistant_id}",
                ),
            ]
        )
    )[0]:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to interact with this assistant.",
        )

    try:
        asst = await models.Assistant.get_by_id(request.state.db, thread.assistant_id)

        # When we reach 3 user messages, or if we failed to generate a title before, generate a new one. Only use the first 100 words of each user and assistant message to maintain a low token count.
        if thread.user_message_ct == 3 or thread.name is None:
            thread.name = await get_thread_conversation_name(
                openai_client,
                request.state.db,
                data,
                thread.thread_id,
                class_id,
            )

        if data.file_search_file_ids:
            if thread.vector_store_id:
                # Vector store already exists, update
                await add_vector_store_files_to_db(
                    request.state.db,
                    thread.vector_store_id,
                    data.file_search_file_ids,
                )
            else:
                # Store doesn't exist, create a new one
                # (empty, since we're adding files as attachments)
                # and relate files with new vector store
                vector_store_id, vector_store_object_id = await create_vector_store(
                    request.state.db,
                    openai_client,
                    class_id,
                    data.file_search_file_ids,
                    type=schemas.VectorStoreType.THREAD,
                    upload_to_oai=False,
                )
                thread.vector_store_id = vector_store_object_id
                tool_resources["file_search"] = {"vector_store_ids": [vector_store_id]}

                existing_file_ids = [
                    file_id
                    async for file_id in models.Thread.get_file_ids_by_id(
                        request.state.db, thread.id
                    )
                ]
                tool_resources["code_interpreter"] = {"file_ids": existing_file_ids}

                try:
                    await openai_client.beta.threads.update(
                        thread.thread_id, tool_resources=tool_resources
                    )
                except openai.BadRequestError as e:
                    raise HTTPException(
                        400,
                        get_details_from_api_error(e, "OpenAI rejected this request"),
                    )

                thread.updated = func.now()

        if data.code_interpreter_file_ids:
            await models.Thread.add_code_interpeter_files(
                request.state.db, thread.id, data.code_interpreter_file_ids
            )

        vision_image_descriptions = None
        if data.vision_image_descriptions:
            vision_image_descriptions = generate_vision_image_descriptions_string(
                data.vision_image_descriptions
            )

        messageContent: MessageContentPartParam = [
            {
                "type": "text",
                "text": data.message + (vision_image_descriptions or ""),
            }
        ]

        if data.vision_file_ids:
            await models.Thread.add_image_files(
                request.state.db, thread.id, data.vision_file_ids
            )
            [
                messageContent.append(
                    {"type": "image_file", "image_file": {"file_id": id}}
                )
                for id in data.vision_file_ids
            ]

        thread.last_activity = func.now()
        thread.user_message_ct += 1
        request.state.db.add(thread)

        metrics.inbound_messages.inc(
            app=config.public_url,
            class_=int(class_id),
            user=request.state.session.user.id,
            thread=thread.thread_id,
        )

        file_names = await models.Thread.get_file_search_files(
            request.state.db, thread.id
        )
        vector_store_id_ = (
            await models.VectorStore.get_vector_store_id_by_id(
                request.state.db, thread.vector_store_id
            )
            if thread.vector_store_id
            else None
        )
        # Create a generator that will stream chunks to the client.
        stream = run_thread(
            openai_client,
            class_id=class_id,
            thread_id=thread.thread_id,
            assistant_id=asst.assistant_id,
            message=messageContent,
            metadata={"user_id": str(request.state.session.user.id)},
            file_names=file_names,
            file_search_file_ids=data.file_search_file_ids,
            code_interpreter_file_ids=data.code_interpreter_file_ids,
            vector_store_id=vector_store_id_,
        )
    except Exception:
        logger.exception("Error running thread")
        raise HTTPException(
            status_code=500,
            detail="We faced an error while sending your message. Please try again later.",
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
    "/class/{class_id}/thread/{thread_id}/file/{file_id}",
    dependencies=[
        Depends(Authz("can_participate", "thread:{thread_id}")),
    ],
)
async def remove_file_from_thread(
    class_id: str,
    thread_id: str,
    file_id: str,
    request: Request,
    openai_client: OpenAIClient,
):
    try:
        await models.File.delete_by_file_id(request.state.db, file_id)
        await openai_client.files.delete(file_id)
    except openai.NotFoundError:
        pass
    except openai.BadRequestError as e:
        raise HTTPException(
            400, get_details_from_api_error(e, "OpenAI rejected this request")
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
    # Detach the vector store from the thread and delete it
    vector_store_obj_id = None
    file_ids_to_delete = []
    if thread.vector_store_id:
        vector_store_id = thread.vector_store_id
        thread.vector_store_id = None
        # Keep the OAI vector store ID for deletion
        result_vector = await delete_vector_store_db_returning_file_ids(
            request.state.db, vector_store_id
        )
        vector_store_obj_id = result_vector.vector_store_id
        file_ids_to_delete.extend(result_vector.deleted_file_ids)

    # Remove any CI files associations with the thread
    stmt = (
        delete(models.code_interpreter_file_thread_association)
        .where(
            models.code_interpreter_file_thread_association.c.thread_id
            == int(thread.id)
        )
        .returning(models.code_interpreter_file_thread_association.c.file_id)
    )
    result_ci = await request.state.db.execute(stmt)
    file_ids_to_delete.extend([row[0] for row in result_ci.fetchall()])

    # Remove any image files associations with the thread
    stmt = (
        delete(models.image_file_thread_association)
        .where(models.image_file_thread_association.c.thread_id == int(thread.id))
        .returning(models.image_file_thread_association.c.file_id)
    )
    result_image = await request.state.db.execute(stmt)
    file_ids_to_delete.extend([row[0] for row in result_image.fetchall()])

    revokes = [(f"class:{class_id}", "parent", f"thread:{thread_id}")] + [
        (f"user:{u.id}", "party", f"thread:{thread_id}") for u in thread.users
    ]

    if not thread.private:
        revokes.append(
            (f"class:{class_id}#member", "can_view", f"thread:{thread.id}"),
        )

    # Keep the OAI thread ID for deletion
    await thread.delete(request.state.db)

    # Delete vector store as late as possible to avoid orphaned thread
    if vector_store_obj_id:
        await delete_vector_store_oai(openai_client, vector_store_obj_id)

    try:
        await openai_client.beta.threads.delete(thread.thread_id)
    except openai.NotFoundError:
        pass
    except openai.BadRequestError as e:
        raise HTTPException(
            400, get_details_from_api_error(e, "OpenAI rejected this request")
        )

    # clean up grants
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
            detail=f"File too large. Max size is {humanize.naturalsize(config.upload.private_file_max_size)}.",
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
    purpose: schemas.FileUploadPurpose = Form("assistants"),
    use_image_descriptions: bool = Form(False),
) -> schemas.File:
    if upload.size > config.upload.private_file_max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size is {humanize.naturalsize(config.upload.private_file_max_size)}.",
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
        use_image_descriptions=use_image_descriptions,
    )


@v1.delete(
    "/class/{class_id}/file/{file_id}",
    dependencies=[Depends(Authz("can_delete", "class_file:{file_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_file(
    class_id: str, file_id: str, request: Request, openai_client: OpenAIClient
):
    try:
        await handle_delete_file(
            request.state.db, request.state.authz, openai_client, int(file_id)
        )
    except FileNotFoundException:
        raise HTTPException(404, "File not found!")
    return {"status": "ok"}


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
    try:
        await handle_delete_file(
            request.state.db, request.state.authz, openai_client, int(file_id)
        )
    except FileNotFoundException:
        raise HTTPException(404, "File not found!")
    return {"status": "ok"}


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
        _model = (
            get_azure_model_deployment_name_equivalent(req.model)
            if isinstance(openai_client, openai.AsyncAzureOpenAI)
            else req.model
        )

        reasoning_effort = (
            REASONING_EFFORT_MAP.get(req.reasoning_effort)
            if req.reasoning_effort is not None
            else None
        )
        reasoning_extra_body = (
            {"reasoning_effort": reasoning_effort}
            if reasoning_effort is not None
            else {}
        )

        new_asst = await openai_client.beta.assistants.create(
            instructions=format_instructions(
                req.instructions,
                use_latex=req.use_latex,
                use_image_descriptions=req.use_image_descriptions,
            ),
            model=_model,
            tools=req.tools,
            temperature=req.temperature,
            metadata={"class_id": class_id, "creator_id": str(creator_id)},
            tool_resources=tool_resources,
            extra_body=reasoning_extra_body,
        )
    except openai.BadRequestError as e:
        raise HTTPException(
            400, get_details_from_api_error(e, "OpenAI rejected this request")
        )
    except openai.NotFoundError as e:
        if e.code == "DeploymentNotFound":
            raise HTTPException(
                404,
                f"Deployment <b>{_model}</b> does not exist on Azure. Please make sure the <b>deployment name</b> matches the one in Azure. If you created the deployment within the last 5 minutes, please wait a moment and try again.",
            )
        raise HTTPException(
            404, get_details_from_api_error(e, "OpenAI rejected this request")
        )

    try:
        # Delete private files uploaded but not attached to the assistant
        await handle_delete_files(
            request.state.db,
            request.state.authz,
            openai_client,
            req.deleted_private_files,
        )

        del req.deleted_private_files

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

    # Users without publish permission can't toggle the published status of assistants.
    if "published" in req.model_fields_set and asst.published != req.published:
        if not await request.state.authz.test(
            f"user:{request.state.session.user.id}",
            "can_publish",
            f"assistant:{assistant_id}",
        ):
            raise HTTPException(
                status_code=403,
                detail="You are not allowed to toggle the published status of assistants for this class.",
            )

    if not req.model_dump():
        return asst

    # Only Administrators can edit locked assistants
    if asst.locked and req.model_fields_set != {"published", "use_image_descriptions"}:
        if not await request.state.authz.test(
            f"user:{request.state.session.user.id}",
            "admin",
            f"class:{class_id}",
        ):
            raise HTTPException(
                403,
                "This assistant is locked and cannot be edited. Please create a new assistant if you need to make changes.",
            )

    openai_update: dict[str, Any] = {}
    tool_resources: ToolResources = {}
    update_tool_resources = False
    update_instructions = False

    # Track whether we have an empty vector store to delete
    vector_store_id_to_delete = None

    try:
        # ------------------- Code Interpreter -------------------
        # Fetch all the code interpreter files associated with the assistant
        # based on the Update request and update the assistant's
        # code interpreter files
        if "code_interpreter_file_ids" in req.model_fields_set:
            update_tool_resources = True
            if (
                req.code_interpreter_file_ids is not None
                and req.code_interpreter_file_ids != []
            ):
                tool_resources["code_interpreter"] = {
                    "file_ids": req.code_interpreter_file_ids
                }
                asst.code_interpreter_files = await models.File.get_all_by_file_id(
                    request.state.db, req.code_interpreter_file_ids
                )
            else:
                asst.code_interpreter_files = []

        # --------------------- File Search ---------------------
        if "file_search_file_ids" in req.model_fields_set:
            update_tool_resources = True
            if req.file_search_file_ids is not None and req.file_search_file_ids != []:
                # Files will need to be stored in a vector store
                if asst.vector_store_id:
                    # Vector store already exists, update
                    vector_store_id = await sync_vector_store_files(
                        request.state.db,
                        openai_client,
                        asst.vector_store_id,
                        req.file_search_file_ids,
                    )
                    tool_resources["file_search"] = {
                        "vector_store_ids": [vector_store_id]
                    }
                else:
                    # Store doesn't exist, create a new one
                    vector_store_id, vector_store_object_id = await create_vector_store(
                        request.state.db,
                        openai_client,
                        class_id,
                        req.file_search_file_ids,
                        type=schemas.VectorStoreType.THREAD,
                    )
                    asst.vector_store_id = vector_store_object_id
                    tool_resources["file_search"] = {
                        "vector_store_ids": [vector_store_id]
                    }
            else:
                # No files stored in vector store, remove it
                if asst.vector_store_id:
                    id_to_delete = asst.vector_store_id
                    asst.vector_store_id = None
                    vector_store_id_to_delete = await delete_vector_store_db(
                        request.state.db, id_to_delete
                    )
                    tool_resources["file_search"] = {}
    except Exception:
        raise HTTPException(
            500, "Error updating assistant files. Please try saving again."
        )

    if update_tool_resources:
        openai_update["tool_resources"] = tool_resources
    if "use_latex" in req.model_fields_set and req.use_latex is not None:
        update_instructions = True
        asst.use_latex = req.use_latex
    if (
        "use_image_descriptions" in req.model_fields_set
        and req.use_image_descriptions is not None
        and asst.use_image_descriptions != req.use_image_descriptions
    ):
        update_instructions = True
        asst.use_image_descriptions = req.use_image_descriptions
    if "hide_prompt" in req.model_fields_set and req.hide_prompt is not None:
        asst.hide_prompt = req.hide_prompt
    if "instructions" in req.model_fields_set and req.instructions is not None:
        update_instructions = True
        if not req.instructions:
            raise HTTPException(400, "Instructions cannot be empty.")
        asst.instructions = req.instructions
    _model = None
    if "model" in req.model_fields_set and req.model is not None:
        _model = (
            get_azure_model_deployment_name_equivalent(req.model)
            if isinstance(openai_client, openai.AsyncAzureOpenAI)
            else req.model
        )
        openai_update["model"] = _model
        asst.model = req.model
    if "description" in req.model_fields_set and req.description is not None:
        asst.description = req.description
    if "tools" in req.model_fields_set and req.tools is not None:
        openai_update["tools"] = req.tools
        asst.tools = json.dumps([t.model_dump() for t in req.tools])

    if "temperature" in req.model_fields_set:
        openai_update["temperature"] = req.temperature
        asst.temperature = req.temperature

    if "reasoning_effort" in req.model_fields_set:
        reasoning_effort = (
            REASONING_EFFORT_MAP.get(req.reasoning_effort)
            if req.reasoning_effort is not None
            else None
        )
        reasoning_extra_body: dict[str, Optional[str]] = (
            {"reasoning_effort": reasoning_effort}
            if reasoning_effort
            else (
                {"reasoning_effort": None} if asst.reasoning_effort is not None else {}
            )
        )
        openai_update["extra_body"] = reasoning_extra_body
        asst.reasoning_effort = req.reasoning_effort

    if (
        "published" in req.model_fields_set
        and req.published is not None
        and req.published != asst.published
    ):
        ptuple = (f"class:{class_id}#member", "can_view", f"assistant:{asst.id}")
        if req.published:
            asst.published = func.now()
            grants.append(ptuple)
        else:
            asst.published = None
            revokes.append(ptuple)

    if "name" in req.model_fields_set and req.name is not None:
        asst.name = req.name

    await models.Thread.update_tools_available(request.state.db, asst.id, asst.tools)
    request.state.db.add(asst)
    await request.state.db.flush()
    await request.state.db.refresh(asst)

    if not asst.instructions:
        raise HTTPException(500, "Instructions cannot be empty.")
    if update_instructions:
        openai_update["instructions"] = format_instructions(
            asst.instructions,
            use_latex=asst.use_latex,
            use_image_descriptions=asst.use_image_descriptions,
        )

    if openai_update:
        try:
            await openai_client.beta.assistants.update(
                assistant_id=asst.assistant_id, **openai_update
            )
            # Delete vector store as late as possible to avoid orphaned assistant
            if vector_store_id_to_delete:
                await delete_vector_store_oai(openai_client, vector_store_id_to_delete)
        except openai.BadRequestError as e:
            raise HTTPException(
                400, get_details_from_api_error(e, "OpenAI rejected this request")
            )
        except openai.NotFoundError as e:
            if e.code == "DeploymentNotFound":
                raise HTTPException(
                    404,
                    f"Deployment <b>{_model}</b> does not exist on Azure. Please make sure the <b>deployment name</b> matches the one in Azure. If you created the deployment within the last 5 minutes, please wait a moment and try again.",
                )
            raise HTTPException(
                404, get_details_from_api_error(e, "OpenAI rejected this request")
            )

    if (
        "deleted_private_files" in req.model_fields_set
        and req.deleted_private_files != []
    ):
        try:
            # Delete any private files that were removed
            await handle_delete_files(
                request.state.db,
                request.state.authz,
                openai_client,
                req.deleted_private_files,
            )
        except Exception as e:
            raise HTTPException(500, f"Error removing private files: {e}")

    await request.state.authz.write_safe(grant=grants, revoke=revokes)
    return asst


@v1.post(
    "/class/{class_id}/assistant/{assistant_id}/publish",
    dependencies=[Depends(Authz("can_publish", "assistant:{assistant_id}"))],
)
async def publish_assistant(class_id: str, assistant_id: str, request: Request):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    asst.published = func.now()
    request.state.db.add(asst)
    await request.state.authz.write_safe(
        grant=[(f"class:{class_id}#member", "can_view", f"assistant:{assistant_id}")]
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}/publish",
    dependencies=[Depends(Authz("can_publish", "assistant:{assistant_id}"))],
)
async def unpublish_assistant(class_id: str, assistant_id: str, request: Request):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    asst.published = None
    request.state.db.add(asst)
    await request.state.authz.write_safe(
        revoke=[(f"class:{class_id}#member", "can_view", f"assistant:{assistant_id}")]
    )
    return {"status": "ok"}


@v1.post(
    "/class/{class_id}/assistant/{assistant_id}/lock",
    dependencies=[Depends(Authz("admin", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def lock_assistant(class_id: str, assistant_id: str, request: Request):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    if not asst:
        raise HTTPException(404, "Assistant not found.")
    asst.locked = True
    request.state.db.add(asst)
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}/lock",
    dependencies=[Depends(Authz("admin", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def unlock_assistant(class_id: str, assistant_id: str, request: Request):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    if not asst:
        raise HTTPException(404, "Assistant not found.")
    asst.locked = False
    request.state.db.add(asst)
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[Depends(Authz("can_delete", "assistant:{assistant_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_assistant(
    class_id: str,
    assistant_id: str,
    request: Request,
    openai_client: OpenAIClient,
):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))

    # Detach the vector store from the assistant and delete it
    vector_store_obj_id = None
    if asst.vector_store_id:
        vector_store_id = asst.vector_store_id
        asst.vector_store_id = None
        # Keep the OAI vector store ID for deletion
        vector_store_obj_id = await delete_vector_store_db(
            request.state.db, vector_store_id
        )

    # Remove any CI files associations with the assistant
    stmt = delete(models.code_interpreter_file_assistant_association).where(
        models.code_interpreter_file_assistant_association.c.assistant_id
        == int(asst.id)
    )
    await request.state.db.execute(stmt)

    revokes = [
        (f"class:{class_id}", "parent", f"assistant:{asst.id}"),
        (f"user:{asst.creator_id}", "owner", f"assistant:{asst.id}"),
    ]

    if asst.published:
        revokes.append(
            (f"class:{class_id}#member", "can_view", f"assistant:{asst.id}"),
        )

    _stmt = (
        update(models.Thread)
        .where(models.Thread.assistant_id == int(asst.id))
        .values(assistant_id=None)
    )
    await request.state.db.execute(_stmt)

    # Keep the OAI assistant ID for deletion
    assistant_id = asst.assistant_id
    await models.Assistant.delete(request.state.db, asst.id)

    # Delete vector store as late as possible to avoid orphaned assistant
    if vector_store_obj_id:
        await delete_vector_store_oai(openai_client, vector_store_obj_id)

    try:
        await openai_client.beta.assistants.delete(assistant_id)
    except openai.NotFoundError:
        pass
    except openai.BadRequestError as e:
        raise HTTPException(
            400, get_details_from_api_error(e, "OpenAI rejected this request")
        )

    # clean up grants
    await request.state.authz.write_safe(revoke=revokes)
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
    "/me/activity_summaries",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.ActivitySummarySubscriptions,
)
async def get_activity_summaries(request: Request):
    """Get the user's activity summaries."""

    # Get all groups the user is a moderator of
    moderator_class_ids = await request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "teacher",
        "class",
    )

    return await models.UserClassRole.get_activity_summary_subscriptions(
        request.state.db, request.state.session.user.id, moderator_class_ids
    )


@v1.post(
    "/me/activity_summaries",
    dependencies=[Depends(LoggedIn())],
)
async def subscribe_to_all_summaries(
    request: Request,
):
    """Subscribe to all activity summaries."""
    moderator_classes = await request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "teacher",
        "class",
    )

    if not moderator_classes:
        raise HTTPException(
            403,
            "You must be a Moderator in at least one class to subscribe to activity summaries.",
        )

    await models.UserClassRole.subscribe_to_all_summaries(
        request.state.db, request.state.session.user.id
    )
    return {"status": "ok"}


@v1.delete(
    "/me/activity_summaries",
    dependencies=[Depends(LoggedIn())],
)
async def unsubscribe_from_all_summaries(
    request: Request,
):
    """Unsubscribe from all activity summaries."""
    moderator_classes = await request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "teacher",
        "class",
    )

    if not moderator_classes:
        raise HTTPException(
            403,
            "You must be a Moderator in at least one class to subscribe to activity summaries.",
        )

    await models.UserClassRole.unsubscribe_from_all_summaries(
        request.state.db, request.state.session.user.id
    )
    return {"status": "ok"}


@v1.post(
    "/me/activity_summaries/create",
    dependencies=[Depends(LoggedIn())],
)
async def enable_dna_as_create(
    request: Request,
):
    """Enable DNA as create."""
    await models.User.update_dna_as_create(
        request.state.db, request.state.session.user.id, True
    )
    return {"status": "ok"}


@v1.delete(
    "/me/activity_summaries/create",
    dependencies=[Depends(LoggedIn())],
)
async def disable_dna_as_create(
    request: Request,
):
    """Disable DNA as create."""
    await models.User.update_dna_as_create(
        request.state.db, request.state.session.user.id, False
    )
    return {"status": "ok"}


@v1.post(
    "/me/activity_summaries/join",
    dependencies=[Depends(LoggedIn())],
)
async def enable_dna_as_join(
    request: Request,
):
    """Enable DNA as join."""
    await models.User.update_dna_as_join(
        request.state.db, request.state.session.user.id, True
    )
    return {"status": "ok"}


@v1.delete(
    "/me/activity_summaries/join",
    dependencies=[Depends(LoggedIn())],
)
async def disable_dna_as_join(
    request: Request,
):
    """Disable DNA as join."""
    await models.User.update_dna_as_join(
        request.state.db, request.state.session.user.id, False
    )
    return {"status": "ok"}


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
    "/admin/providers",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.ExternalLoginProviders,
)
async def get_external_login_providers(request: Request):
    """Get the external login providers."""
    providers = await models.ExternalLoginProvider.get_all(request.state.db)
    return {"providers": providers}


@v1.put(
    "/admin/providers/{provider_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def update_external_login_provider(
    provider_id: str,
    req: schemas.UpdateExternalLoginProvider,
    request: Request,
):
    """Update an external login provider."""
    provider = await models.ExternalLoginProvider.get_by_id(
        request.state.db, int(provider_id)
    )
    if not provider:
        raise HTTPException(404, "Provider not found.")
    provider.description = req.description
    provider.display_name = req.display_name
    request.state.db.add(provider)
    await request.state.db.flush()
    return {"status": "ok"}


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
