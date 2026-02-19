import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from collections import defaultdict
from datetime import datetime, timedelta
from math import ceil
from typing import Annotated, Any, Literal, Optional, Union, cast
import uuid_utils as uuid
from aiohttp import ClientResponseError
import jwt
import openai
import humanize
from email_validator import EmailSyntaxError, validate_email
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import (
    BackgroundTasks,
    Body,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import PositiveInt
from openai.types.responses.response_output_text import AnnotationURLCitation
from openai.types.responses.response_function_web_search import (
    ActionFind,
    ActionOpenPage,
    ActionSearch,
    ActionSearchSource,
)
from openai.types.beta.threads.message import Attachment
from openai.types.beta.threads.image_file_content_block import ImageFileContentBlock
from openai.types.beta.threads.image_file import ImageFile
from openai.types.beta.threads.annotation import Annotation
from openai.types.beta.threads.file_path_annotation import FilePathAnnotation, FilePath
from openai.types.beta.threads.file_citation_annotation import (
    FileCitationAnnotation,
    FileCitation,
)

from pingpong.ai_models import (
    AZURE_UNAVAILABLE_MODELS,
    DEFAULT_PROMPTS,
    KNOWN_MODELS,
    ADMIN_ONLY_MODELS,
    HIDDEN_MODELS,
    get_reasoning_effort_map,
)
from pingpong.artifacts import ArtifactStoreError
from pingpong.audio_store import AudioStoreError
from pingpong.bg_tasks import safe_task
from pingpong.copy import copy_group, copy_assistant as copy_assistant_to_class
from pingpong.emails import (
    parse_addresses,
    revalidate_email_addresses,
    validate_email_addresses,
)
from pingpong.invite import (
    send_lti_registration_approved,
    send_lti_registration_rejected,
)
from pingpong.lti.lti_course import (
    find_class_by_course_id,
    find_class_by_course_id_search_by_canvas_account_lti_guid,
)
from pingpong.realtime import browser_realtime_websocket
from pingpong.session import populate_request
from pingpong.stats import (
    get_runs_with_multiple_assistant_messages_stats,
    get_statistics,
    get_statistics_by_institution as get_institution_statistics,
    get_thread_counts_by_class,
)
from pingpong.summary import send_class_summary_to_user_task
from pingpong.video_store import VideoStoreError
from .animal_hash import name, process_threads, pseudonym, user_names
from openai.types.beta.assistant_create_params import ToolResources
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
    GetOpenAIClientException,
    export_class_threads_anonymized,
    export_threads_multiple_classes,
    format_instructions,
    get_openai_client_by_class_id,
    get_original_model_name_by_azure_equivalent,
    get_thread_conversation_name,
    get_initial_thread_conversation_name,
    inject_timestamp_to_instructions,
    run_response,
    run_thread,
    upgrade_assistants_model,
    validate_api_key,
    get_ci_messages_from_step,
    get_azure_model_deployment_name_equivalent,
)
from .ai_error import get_details_from_api_error
from .auth import (
    decode_auth_token,
    generate_auth_link,
    redirect_with_session,
)
from .authz import Relation
from .config import config
from .lti.canvas_connect import (
    CanvasConnectException,
    CanvasConnectWarning,
    ManualCanvasConnectClient,
)
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
from .permission import Authz, InstitutionAdmin, LoggedIn, ClassInstitutionAdmin
from .runs import get_placeholder_ci_calls
from .state_types import AppState, StateRequest, StateWebSocket
from .vector_stores import (
    add_vector_store_files_to_db,
    append_vector_store_files,
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
from .transcription import transcribe_thread_recording_and_email_link

logger = logging.getLogger(__name__)
responses_api_transition_logger = logging.getLogger("responses_api_transition")


def allowed_assistant_message_ids(
    messages: list[models.Message],
    tool_calls: list[models.ToolCall],
    reasoning_steps: list[models.ReasoningStep],
) -> set[int]:
    """Return assistant message IDs that are not consecutive with another assistant message in the same run."""
    allowed_ids: set[int] = {
        message.id
        for message in messages
        if message.run_id is None or message.role != schemas.MessageRole.ASSISTANT
    }
    items_by_run: dict[
        int,
        list[
            tuple[
                int,
                str,
                models.Message | models.ToolCall | models.ReasoningStep,
            ]
        ],
    ] = defaultdict(list)

    for message in messages:
        if message.run_id is None:
            continue
        items_by_run[message.run_id].append((message.output_index, "message", message))
    for tool_call in tool_calls:
        if tool_call.run_id is None:
            continue
        items_by_run[tool_call.run_id].append(
            (tool_call.output_index, "tool_call", tool_call)
        )
    for reasoning_step in reasoning_steps:
        if reasoning_step.run_id is None:
            continue
        items_by_run[reasoning_step.run_id].append(
            (reasoning_step.output_index, "reasoning", reasoning_step)
        )

    for items in items_by_run.values():
        items.sort(key=lambda item: item[0])
        previous_type: str | None = None
        for _, item_type, obj in items:
            if item_type == "message":
                message_obj = obj  # type: ignore[assignment]
                if message_obj.role == schemas.MessageRole.ASSISTANT:
                    if previous_type == "assistant_message":
                        continue
                    allowed_ids.add(message_obj.id)
                    previous_type = "assistant_message"
                else:
                    previous_type = "other_message"
            else:
                previous_type = item_type

    return allowed_ids


async def _direct_institution_admin_ids(authz: Any, inst_id: int) -> list[int]:
    tuples = await authz.read_tuples("admin", f"institution:{inst_id}", user=None)
    admin_ids: list[int] = []
    for user, _, _ in tuples:
        if not user or not user.startswith("user:"):
            continue
        try:
            admin_ids.append(int(user.split(":")[1]))
        except (IndexError, ValueError):
            continue
    return admin_ids


if config.development:
    v1 = FastAPI()
else:
    v1 = FastAPI(
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )


def get_now_fn(req: StateRequest) -> NowFn:
    """Get the current time function for the request."""
    app_state = cast(AppState, req.app.state)
    return app_state["now"] if "now" in app_state else utcnow


OpenAIClientType = Union[openai.AsyncClient, openai.AsyncAzureOpenAI]


async def get_openai_client_for_class(request: StateRequest) -> OpenAIClientType:
    """Get an OpenAI client for the class.

    Requires the class_id to be in the path parameters.
    """
    class_id = request.path_params["class_id"]
    try:
        return await get_openai_client_by_class_id(request.state["db"], int(class_id))
    except GetOpenAIClientException as e:
        raise HTTPException(status_code=e.code, detail=e.detail)


OpenAIClientDependency = Depends(get_openai_client_for_class)
OpenAIClient = Annotated[OpenAIClientType, OpenAIClientDependency]


@v1.middleware("http")
async def parse_session_token(request: StateRequest, call_next):
    """Parse the session token from the cookie and add it to the request state."""
    request = await populate_request(request)
    return await call_next(request)


@v1.middleware("http")
async def begin_authz_session(request: StateRequest, call_next):
    """Connect to authorization server."""
    async with config.authz.driver.get_client() as c:
        request.state["authz"] = c
        response = await call_next(request)
        await c.close()
        return response


@v1.middleware("http")
async def begin_db_session(request: StateRequest, call_next):
    """Create a database session for the request."""
    async with config.db.driver.async_session_with_args(pool_pre_ping=True)() as db:
        request.state["db"] = db
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
async def log_request(request: StateRequest, call_next):
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
def get_config(request: StateRequest):
    d = config.model_dump()
    for k in d.get("auth", {}).get("secret_keys", []):
        k["key"] = "******"
    if "key" in d.get("authz", {}):
        d["authz"]["key"] = "******"
    if "password" in d.get("db", {}):
        d["db"]["password"] = "******"
    if "webhook" in d.get("support", {}):
        d["support"]["webhook"] = "******"
    for instance in d.get("lms", {}).get("lms_instances", []):
        if "client_secret" in instance:
            instance["client_secret"] = "******"
    return {"config": d, "headers": dict(request.headers)}


@v1.get(
    "/authz/audit",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.InspectAuthz,
)
async def inspect_authz(request: StateRequest, subj: str, obj: str, rel: str):
    subj_type_, _, subj_id_ = subj.partition(":")
    obj_type_, _, obj_id_ = obj.partition(":")
    try:
        result: schemas.InspectAuthzResult | None = None
        if obj_id_ and subj_id_:
            logger.info(f"Inspecting authz for {subj} {rel} {obj}")
            verdict = await request.state["authz"].test(subj, rel, obj)
            result = schemas.InspectAuthzTestResult(
                verdict=verdict,
            )
        elif subj_id_:
            ids = await request.state["authz"].list(subj, rel, obj)
            result = schemas.InspectAuthzListResult(
                list=ids,
            )
        elif obj_id_ and (subj_type_ == "user"):
            ids = await request.state["authz"].list_entities(obj, rel, subj_type_)
            result = schemas.InspectAuthzListResult(
                list=ids,
            )
        elif obj_id_ and (
            subj_type_ == "anonymous_user" or subj_type_ == "anonymous_link"
        ):
            ids = await request.state["authz"].list_entities_permissive(
                obj, rel, subj_type_
            )
            result = schemas.InspectAuthzListResultPermissive(
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


@v1.get(
    "/authz/audit_all",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.InspectAuthzAllResult,
)
async def list_all_user_permissions(request: StateRequest, user_id: str):
    return {"result": await list_all_permissions(request.state["authz"], int(user_id))}


@v1.post(
    "/authz/audit",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def manage_authz(data: schemas.ManageAuthzRequest, request: StateRequest):
    await request.state["authz"].write(grant=data.grant, revoke=data.revoke)
    return {"status": "ok"}


@v1.post("/login/sso/saml/acs", response_model=schemas.GenericStatus)
async def login_sso_saml_acs(provider: str, request: StateRequest):
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

    if not attrs.email:
        raise HTTPException(
            status_code=400, detail="SAML response does not contain an email address"
        )

    # Create user if missing. Update if already exists.
    user = await models.User.get_by_email_sso(
        request.state["db"],
        attrs.email,
        provider,
        attrs.identifier if attrs.identifier else None,
    )
    if not user:
        user = models.User(
            email=attrs.email,
        )

    # Update user info
    user.email = attrs.email
    if attrs.first_name:
        user.first_name = attrs.first_name
    if attrs.last_name:
        user.last_name = attrs.last_name
    if attrs.name:
        user.display_name = attrs.name
    user.state = schemas.UserState.VERIFIED

    # Save user to DB
    request.state["db"].add(user)
    await request.state["db"].flush()
    await request.state["db"].refresh(user)

    if attrs.identifier:
        # Add external login and get accounts to merge
        await models.ExternalLogin.create_or_update(
            request.state["db"],
            user.id,
            provider=provider,
            identifier=attrs.identifier,
            called_by="login_sso_saml_acs",
        )
        user_ids = await models.ExternalLogin.accounts_to_merge(
            request.state["db"], user.id, provider=provider, identifier=attrs.identifier
        )

        # Merge accounts
        for uid in user_ids:
            await merge(request.state["db"], request.state["authz"], user.id, uid)

    url = "/"
    if "RelayState" in saml_client._request_data["get_data"]:
        url = saml_client._request_data["get_data"]["RelayState"]
    elif "RelayState" in saml_client._request_data["post_data"]:
        url = saml_client._request_data["post_data"]["RelayState"]
    next_url = saml_client.redirect_to(url)
    return redirect_with_session(next_url, user.id, nowfn=get_now_fn(request))


@v1.get("/login/sso")
async def login_sso(provider: str, request: StateRequest):
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
async def get_user_by_email(email: str, request: StateRequest):
    _email = email.lower().strip()
    user = await models.User.get_by_email_sso(
        request.state["db"], _email, "email", _email
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@v1.get(
    "/user/{user_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.User,
)
async def get_user(user_id: str, request: StateRequest):
    user = await models.User.get_by_id(request.state["db"], int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@v1.get(
    "/user/{user_id}/email",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.ExternalLogins,
)
async def get_secondary_emails(user_id: str, request: StateRequest):
    user = await models.User.get_by_id(request.state["db"], int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    external_logins = await models.ExternalLogin.get_secondary_emails_by_user_id(
        request.state["db"], user.id
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
async def add_email_to_user(user_id: str, email: str, request: StateRequest):
    _new_email = email.lower().strip()
    email_verification = parse_addresses(_new_email)

    if not email_verification[0].valid:
        raise HTTPException(status_code=400, detail="Invalid new email address.")

    user = await models.User.get_by_id(request.state["db"], int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        is_new_or_updated = await models.ExternalLogin.create_or_update(
            request.state["db"],
            user.id,
            provider="email",
            identifier=_new_email,
            called_by="add_email_to_user",
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
async def delete_email_from_user(user_id: str, email: str, request: StateRequest):
    user = await models.User.get_by_id(request.state["db"], int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        await models.ExternalLogin.delete_secondary_email(
            request.state["db"], user.id, email=email
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
    old_user_id: PositiveInt, new_user_id: PositiveInt, request: StateRequest
):
    await merge(request.state["db"], request.state["authz"], new_user_id, old_user_id)
    return {"status": "ok"}


@v1.post("/login/magic", response_model=schemas.GenericStatus)
async def login_magic(body: schemas.MagicLoginRequest, request: StateRequest):
    """Provide a magic link to the auth endpoint."""
    # First figure out if this email domain is even allowed to use magic auth.
    # If not, we deny the request and point to another place they can log in.
    # Validate the email address format
    try:
        validate_email(body.email, check_deliverability=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid email address.")
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
    user = await models.User.get_by_email_sso(
        request.state["db"], email, "email", email
    )
    # Throw an error if the user does not exist.
    if not user:
        # In dev we can auto-create the user as a super-admin
        if config.auth.autopromote_on_login:
            if not config.development:
                raise RuntimeError("Cannot autopromote in non-dev mode")
            user = await models.User.get_or_create_by_email(request.state["db"], email)
            user.super_admin = True
            request.state["db"].add(user)
            await request.state["authz"].create_root_user(user.id)
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
async def auth_canvas(request: StateRequest):
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

    if not code or not canvas_settings or user_id != request.state["session"].user.id:
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
async def auth(request: StateRequest):
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
        user = await models.User.get_by_id(request.state["db"], int(e.user_id))
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

    user = await models.User.get_by_id(request.state["db"], int(auth_token.sub))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Figure out the appropriate continuation based on the user's authn method.
    # Currently we do find the authn method by checking the email domain against
    # our config, but in the future we might need to store this explicitly by user
    # in the database.
    login_config = authn_method_for_email(config.auth.authn_methods, user.email)

    if login_config.method == "sso":
        sso_path = f"/api/v1/login/sso?provider={login_config.provider}&redirect={dest}"
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
    dependencies=[Depends(Authz("admin") | InstitutionAdmin())],
    response_model=schemas.DefaultAPIKeys,
)
async def list_default_api_keys(request: StateRequest):
    default_api_keys = await models.APIKey.get_all_default_keys(request.state["db"])
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
async def list_institutions(request: StateRequest, role: str = "can_view"):
    ids = await request.state["authz"].list(
        f"user:{request.state['session'].user.id}", role, "institution"
    )
    inst = await models.Institution.get_all_by_id(request.state["db"], ids)
    return {"institutions": inst}


@v1.post(
    "/institution",
    dependencies=[Depends(Authz("can_create_institution"))],
    response_model=schemas.Institution,
)
async def create_institution(create: schemas.CreateInstitution, request: StateRequest):
    inst = await models.Institution.create(request.state["db"], create)
    await request.state["authz"].grant(
        request.state["authz"].root,
        "parent",
        f"institution:{inst.id}",
    )
    return inst


@v1.get(
    "/admin/institutions",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.Institutions,
)
async def list_institutions_with_admins(request: StateRequest):
    institutions = await models.Institution.get_all(request.state["db"])

    return {"institutions": institutions}


@v1.get(
    "/admin/institutions/{institution_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.InstitutionWithAdmins,
)
async def get_institution_with_admins(institution_id: int, request: StateRequest):
    institution = await models.Institution.get_by_id(
        request.state["db"], institution_id
    )
    if not institution:
        raise HTTPException(status_code=404, detail="Institution not found")

    root_admin_ids = await request.state["authz"].list_entities(
        request.state["authz"].root, "admin", "user"
    )

    inst_admin_ids = await _direct_institution_admin_ids(
        request.state["authz"], institution_id
    )
    all_ids = set(root_admin_ids) | set(inst_admin_ids)
    users_by_id: dict[int, models.User] = {}
    if all_ids:
        users = await models.User.get_all_by_id(request.state["db"], list(all_ids))
        users_by_id = {user.id: user for user in users}

    admins = [
        schemas.InstitutionAdmin.model_validate(
            users_by_id[user_id], from_attributes=True
        )
        for user_id in inst_admin_ids
        if user_id in users_by_id
    ]
    root_admins = [
        schemas.InstitutionAdmin.model_validate(
            users_by_id[user_id], from_attributes=True
        )
        for user_id in root_admin_ids
        if user_id in users_by_id
    ]

    inst_data = schemas.Institution.model_validate(
        institution, from_attributes=True
    ).model_dump()
    return schemas.InstitutionWithAdmins(
        **inst_data, admins=admins, root_admins=root_admins
    )


@v1.patch(
    "/admin/institutions/{institution_id}/default_api_key",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.Institution,
)
async def set_institution_default_api_key(
    institution_id: int,
    body: schemas.SetInstitutionDefaultAPIKeyRequest,
    request: StateRequest,
):
    institution = await models.Institution.get_by_id(
        request.state["db"], institution_id
    )
    if not institution:
        raise HTTPException(status_code=404, detail="Institution not found")

    default_api_key_id = None
    if body.default_api_key_id is not None:
        api_key = await models.APIKey.get_by_id(
            request.state["db"], body.default_api_key_id
        )
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")
        if not api_key.available_as_default:
            raise HTTPException(
                status_code=400, detail="API key is not available as default"
            )
        default_api_key_id = api_key.id
    stmt = (
        update(models.Institution)
        .where(models.Institution.id == int(institution_id))
        .values(default_api_key_id=default_api_key_id)
    )
    await request.state["db"].execute(stmt)
    return await models.Institution.get_by_id(request.state["db"], institution_id)


@v1.post(
    "/admin/institutions/{institution_id}/copy",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.Institution,
)
async def copy_institution(
    institution_id: int, body: schemas.CopyInstitution, request: StateRequest
):
    source = await models.Institution.get_by_id(request.state["db"], institution_id)
    if not source:
        raise HTTPException(status_code=404, detail="Institution not found")

    # Gather direct admins (exclude inherited root) from source.
    admin_ids = await _direct_institution_admin_ids(
        request.state["authz"], institution_id
    )

    # Create the new institution.
    new_inst = await models.Institution.create(
        request.state["db"], schemas.CreateInstitution(name=body.name)
    )
    await request.state["authz"].grant(
        request.state["authz"].root,
        "parent",
        f"institution:{new_inst.id}",
    )

    # Copy admin grants.
    if admin_ids:
        await request.state["authz"].write_safe(
            grant=[
                (f"user:{uid}", "admin", f"institution:{new_inst.id}")
                for uid in admin_ids
            ]
        )

    return new_inst


@v1.get(
    "/institution/{institution_id}",
    dependencies=[Depends(Authz("can_view", "institution:{institution_id}"))],
    response_model=schemas.Institution,
)
async def get_institution(institution_id: str, request: StateRequest):
    return await models.Institution.get_by_id(request.state["db"], int(institution_id))


@v1.patch(
    "/institution/{institution_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.Institution,
)
async def update_institution(
    institution_id: int, data: schemas.UpdateInstitution, request: StateRequest
):
    institution = await models.Institution.update(
        request.state["db"], institution_id, data
    )
    if not institution:
        raise HTTPException(status_code=404, detail="Institution not found")
    return institution


@v1.post(
    "/institution/{institution_id}/admin",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.InstitutionAdminResponse,
)
async def add_institution_admin(
    institution_id: str, data: schemas.AddInstitutionAdminRequest, request: StateRequest
):
    """Add an admin to an institution.

    If a user with the given email does not exist, creates a new user with that email.
    Then grants admin permissions for the specified institution to the user.
    Returns information about whether a user was created and whether admin rights were added.
    """
    inst_id = int(institution_id)
    institution = await models.Institution.get_by_id(request.state["db"], inst_id)
    if not institution:
        raise HTTPException(status_code=404, detail="Institution not found")

    try:
        normalized_email = validate_email(
            data.email, check_deliverability=False
        ).normalized
    except EmailSyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Invalid email: {str(e)}")

    user = await models.User.get_or_create_by_email(
        request.state["db"],
        normalized_email,
        initial_state=schemas.UserState.UNVERIFIED,
    )

    tuples = await request.state["authz"].read_tuples(
        "admin",
        f"institution:{inst_id}",
        user=f"user:{user.id}",
    )
    already_admin = bool(tuples)
    added_admin = False
    if not already_admin:
        await request.state["authz"].write_safe(
            grant=[(f"user:{user.id}", "admin", f"institution:{inst_id}")]
        )
        added_admin = True

    return schemas.InstitutionAdminResponse(
        institution_id=inst_id,
        user_id=user.id,
        email=user.email,
        added_admin=added_admin,
    )


@v1.delete(
    "/institution/{institution_id}/admin/{user_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def remove_institution_admin(
    institution_id: int, user_id: int, request: StateRequest
):
    institution = await models.Institution.get_by_id(
        request.state["db"], institution_id
    )
    if not institution:
        raise HTTPException(status_code=404, detail="Institution not found")

    await request.state["authz"].write_safe(
        revoke=[(f"user:{user_id}", "admin", f"institution:{institution_id}")]
    )
    return {"status": "ok"}


@v1.get(
    "/admin/lti/registrations",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.LTIRegistrations,
)
async def list_lti_registrations(request: StateRequest):
    registrations = await models.LTIRegistration.get_all(request.state["db"])
    return {"registrations": registrations}


@v1.get(
    "/admin/lti/registrations/{registration_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.LTIRegistrationDetail,
)
async def get_lti_registration(registration_id: int, request: StateRequest):
    registration = await models.LTIRegistration.get_by_id(
        request.state["db"], registration_id
    )
    if not registration:
        raise HTTPException(status_code=404, detail="LTI registration not found")

    detail = schemas.LTIRegistrationDetail.model_validate(registration)
    return detail.model_copy(
        update={"lti_classes_count": len(registration.lti_classes or [])}
    )


@v1.patch(
    "/admin/lti/registrations/{registration_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.LTIRegistration,
)
async def update_lti_registration(
    registration_id: int,
    body: schemas.UpdateLTIRegistration,
    request: StateRequest,
):
    data = body.model_dump(exclude_unset=True)
    registration = await models.LTIRegistration.update(
        request.state["db"],
        registration_id,
        data,
        reviewer_id=request.state["session"].user.id,
    )
    if not registration:
        raise HTTPException(status_code=404, detail="LTI registration not found")
    return registration


@v1.patch(
    "/admin/lti/registrations/{registration_id}/status",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.LTIRegistration,
)
async def set_lti_registration_status(
    registration_id: int,
    body: schemas.SetLTIRegistrationStatus,
    request: StateRequest,
):
    # Get current registration to check previous status and get admin email
    current_registration = await models.LTIRegistration.get_by_id(
        request.state["db"], registration_id
    )
    if not current_registration:
        raise HTTPException(status_code=404, detail="LTI registration not found")

    previous_status = current_registration.review_status

    data: dict[str, Any] = {"review_status": body.review_status}
    if body.review_status == schemas.LTIRegistrationReviewStatus.APPROVED:
        data["enabled"] = True
    else:
        data["enabled"] = False
    registration = await models.LTIRegistration.update(
        request.state["db"],
        registration_id,
        data,
        reviewer_id=request.state["session"].user.id,
    )

    if not registration:
        raise HTTPException(status_code=404, detail="LTI registration not found")

    # Send email notification if status changed and admin email exists
    if previous_status != body.review_status and registration.admin_email:
        integration_name = (
            registration.friendly_name
            or registration.canvas_account_name
            or "LTI Integration"
        )
        admin_name = registration.admin_name or "Admin"

        try:
            if body.review_status == schemas.LTIRegistrationReviewStatus.APPROVED:
                await send_lti_registration_approved(
                    config.email.sender,
                    admin_email=registration.admin_email,
                    admin_name=admin_name,
                    integration_name=integration_name,
                )
            elif body.review_status == schemas.LTIRegistrationReviewStatus.REJECTED:
                await send_lti_registration_rejected(
                    config.email.sender,
                    admin_email=registration.admin_email,
                    admin_name=admin_name,
                    integration_name=integration_name,
                    review_notes=registration.review_notes,
                )
        except Exception:
            logging.exception(
                f"Failed to send LTI registration status email: {registration.admin_email}"
            )

    return registration


@v1.patch(
    "/admin/lti/registrations/{registration_id}/enabled",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.LTIRegistration,
)
async def set_lti_registration_enabled(
    registration_id: int,
    body: schemas.SetLTIRegistrationEnabled,
    request: StateRequest,
):
    # First get the registration to check its status
    registration = await models.LTIRegistration.get_by_id(
        request.state["db"], registration_id
    )
    if not registration:
        raise HTTPException(status_code=404, detail="LTI registration not found")
    # Only allow enabling if registration is approved
    if (
        body.enabled
        and registration.review_status != schemas.LTIRegistrationReviewStatus.APPROVED
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot enable registration that is not approved",
        )
    registration = await models.LTIRegistration.set_enabled(
        request.state["db"], registration_id, body.enabled
    )
    return registration


@v1.patch(
    "/admin/lti/registrations/{registration_id}/institutions",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.LTIRegistration,
)
async def set_lti_registration_institutions(
    registration_id: int,
    body: schemas.SetLTIRegistrationInstitutions,
    request: StateRequest,
):
    registration = await models.LTIRegistration.set_institutions(
        request.state["db"], registration_id, body.institution_ids
    )
    if not registration:
        raise HTTPException(status_code=404, detail="LTI registration not found")
    return registration


@v1.get(
    "/admin/lti/institutions",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.InstitutionsWithDefaultAPIKey,
)
async def get_institutions_with_default_api_key(request: StateRequest):
    institutions = await models.Institution.get_all_with_default_api_key(
        request.state["db"]
    )
    return {"institutions": institutions}


@v1.get(
    "/admin/lti/client/{client_id}/course/{course_id}",
    dependencies=[Depends(Authz("admin"))],
)
async def get_lti_class_link(client_id: str, course_id: str, request: StateRequest):
    registration = await models.LTIRegistration.get_by_client_id(
        request.state["db"], client_id
    )
    if registration is None:
        raise HTTPException(status_code=404, detail="Unknown LTI client_id")

    if registration.canvas_account_lti_guid:
        class_ = await find_class_by_course_id_search_by_canvas_account_lti_guid(
            request.state["db"],
            registration_id=registration.id,
            canvas_account_lti_guid=registration.canvas_account_lti_guid,
            course_id=course_id,
        )
    else:
        class_ = await find_class_by_course_id(
            request.state["db"],
            registration.id,
            course_id,
        )

    return {"result": class_}


@v1.get(
    "/institution/{institution_id}/classes",
    dependencies=[Depends(Authz("can_view", "institution:{institution_id}"))],
    response_model=schemas.Classes,
)
async def get_institution_classes(institution_id: str, request: StateRequest):
    classes = await models.Class.get_by_institution(
        request.state["db"], int(institution_id)
    )
    return {"classes": classes}


@v1.post(
    "/institution/{institution_id}/class",
    dependencies=[Depends(Authz("can_create_class", "institution:{institution_id}"))],
    response_model=schemas.Class,
)
async def create_class(
    institution_id: str, create: schemas.CreateClass, request: StateRequest
):
    if not create.any_can_publish_assistant:
        create.any_can_share_assistant = False
    new_class = await models.Class.create(
        request.state["db"], int(institution_id), create
    )

    user = await models.User.get_by_id(
        request.state["db"], request.state["session"].user.id
    )

    # Create an entry for the creator as the owner
    ucr = models.UserClassRole(
        user_id=request.state["session"].user.id,
        class_id=new_class.id,
        subscribed_to_summaries=not user.dna_as_create,
    )
    request.state["db"].add(ucr)

    grants = [
        (f"institution:{institution_id}", "parent", f"class:{new_class.id}"),
        (
            f"user:{request.state['session'].user.id}",
            "teacher",
            f"class:{new_class.id}",
        ),
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

        if new_class.any_can_share_assistant:
            grants.append(
                (
                    f"class:{new_class.id}#student",
                    "can_share_assistants",
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

    await request.state["authz"].write(grant=grants)

    return new_class


@v1.get(
    "/stats",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.StatisticsResponse,
)
async def get_stats(request: StateRequest):
    statistics = await get_statistics(request.state["db"])
    return schemas.StatisticsResponse(statistics=statistics)


@v1.get(
    "/stats/models",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.ModelStatisticsResponse,
)
async def get_models_stats(request: StateRequest):
    counts = await models.Assistant.get_count_by_model(request.state["db"])
    stats = [{"model": k, "assistant_count": v} for (k, v) in counts]
    return schemas.ModelStatisticsResponse(statistics=stats)


@v1.get(
    "/stats/runs",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.RunDailyAssistantMessageStatsResponse,
)
async def get_runs_multi_assistant_stats(
    request: StateRequest,
    days: int = 14,
    group_by: Literal["model", "assistant"] = "model",
    top_n: int = 10,
    summary_only: bool = False,
    sort_priority: Literal["count", "percentage"] = "percentage",
):
    statistics, summary = await get_runs_with_multiple_assistant_messages_stats(
        request.state["db"],
        days=days,
        group_by=group_by,
        limit=top_n,
        summary_only=summary_only,
        sort_priority=sort_priority,
    )
    return schemas.RunDailyAssistantMessageStatsResponse(
        statistics=statistics, summary=summary
    )


@v1.get(
    "/stats/institutions/{institution_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.StatisticsResponse,
)
async def get_stats_by_institution(institution_id: int, request: StateRequest):
    statistics = await get_institution_statistics(request.state["db"], institution_id)
    return schemas.StatisticsResponse(statistics=statistics)


@v1.get(
    "/stats/institutions/{institution_id}/threads",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.InstitutionClassThreadCountsResponse,
)
async def get_thread_counts_for_institution(institution_id: int, request: StateRequest):
    thread_counts = await get_thread_counts_by_class(
        request.state["db"], institution_id
    )
    return schemas.InstitutionClassThreadCountsResponse(
        institution_id=institution_id, classes=thread_counts
    )


@v1.get(
    "/stats/models/{model_name}/assistants",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.AssistantModelInfoResponse,
)
async def get_model_assistants(model_name: str, request: StateRequest):
    assistants = await models.Assistant.get_by_model_with_stats(
        request.state["db"], model_name
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
async def get_my_classes(request: StateRequest):
    ids = await request.state["authz"].list(
        f"user:{request.state['session'].user.id}",
        "can_view",
        "class",
    )
    classes = await models.Class.get_all_by_id(request.state["db"], ids)
    return {"classes": classes}


@v1.get(
    "/class/{class_id}",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.Class,
)
async def get_class(class_id: str, request: StateRequest):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    class_.download_link_expiration = convert_seconds(
        config.artifact_store.download_link_expiration
    )
    class_.ai_provider = (
        class_.api_key_obj.provider
        if class_.api_key_obj
        else ("openai" if class_.api_key else None)
    )
    return class_


@v1.get(
    "/class/{class_id}/upload_info",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.FileUploadSupport,
)
async def get_class_upload_info(class_id: str, request: StateRequest):
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
async def update_class(
    class_id: str, update: schemas.UpdateClass, request: StateRequest
):
    try:
        if (
            update.any_can_publish_assistant is not None
            and not update.any_can_publish_assistant
        ):
            update.any_can_share_assistant = False
        cls = await models.Class.update(request.state["db"], int(class_id), update)
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
    can_share_asst = (
        f"class:{class_id}#student",
        "can_share_assistants",
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

    if cls.any_can_share_assistant and not cls.any_can_publish_assistant:
        grants.append(can_share_asst)
    else:
        revokes.append(can_share_asst)

    if cls.any_can_publish_assistant:
        grants.append(can_pub_asst)
    else:
        revokes.append(can_pub_asst)
        revokes.append(can_share_asst)

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

    await request.state["authz"].write_safe(grant=grants, revoke=revokes)

    return cls


@v1.post(
    "/class/{class_id}/transfer",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.Class,
)
async def transfer_class(
    class_id: str, transfer: schemas.TransferClassRequest, request: StateRequest
):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Class not found")

    if transfer.institution_id == class_.institution_id:
        return class_

    target_institution = await models.Institution.get_by_id(
        request.state["db"], transfer.institution_id
    )
    if not target_institution:
        raise HTTPException(status_code=404, detail="Institution not found")

    if class_.institution_id is None:
        raise HTTPException(
            status_code=400, detail="This group is not linked to an institution."
        )

    checks: list[tuple[int, str]] = [
        (
            class_.institution_id,
            "You do not have permission to create a class in the current institution.",
        ),
        (
            transfer.institution_id,
            "You do not have permission to create a class in the target institution.",
        ),
    ]
    for inst_id, error_detail in checks:
        can_create = await request.state["authz"].test(
            request.state["auth_user"],
            "can_create_class",
            f"institution:{inst_id}",
        )
        if not can_create:
            raise HTTPException(status_code=403, detail=error_detail)

    updated_class, previous_institution_id = await models.Class.transfer_institution(
        request.state["db"], int(class_id), transfer.institution_id
    )

    grants = [
        (
            f"institution:{transfer.institution_id}",
            "parent",
            f"class:{class_id}",
        )
    ]
    revokes = []
    if previous_institution_id is not None:
        revokes.append(
            (
                f"institution:{previous_institution_id}",
                "parent",
                f"class:{class_id}",
            )
        )

    await request.state["authz"].write_safe(grant=grants, revoke=revokes)

    return updated_class


@v1.delete(
    "/class/{class_id}",
    dependencies=[Depends(Authz("can_delete", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_class(class_id: str, request: StateRequest):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Group not found")

    if class_.api_key or class_.api_key_id:
        openai_client = await get_openai_client_for_class(request)
        # Delete all threads
        async for thread in models.Thread.get_ids_by_class_id(
            request.state["db"], class_.id
        ):
            await delete_thread(class_id, str(thread.id), request, openai_client)

        # Delete all class assistants
        async for assistant_id in models.Assistant.async_get_by_class_id(
            request.state["db"], class_.id
        ):
            await delete_assistant(class_id, str(assistant_id), request, openai_client)

        # Double check that we deleted all vector stores
        async for vector_store_id in models.VectorStore.get_id_by_class_id(
            request.state["db"], class_.id
        ):
            await delete_vector_store(
                request.state["db"], openai_client, vector_store_id
            )

    # All private and class files associated with the class_id
    # are deleted by the database cascade
    if class_.lms_status and class_.lms_status not in {
        schemas.LMSStatus.DISMISSED,
        schemas.LMSStatus.NONE,
    }:
        await remove_canvas_connection(request.state["db"], class_.id, request=request)

    stmt = delete(models.UserClassRole).where(
        models.UserClassRole.class_id == class_.id
    )
    await request.state["db"].execute(stmt)

    await class_.delete(request.state["db"])
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/lti/classes",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.LTIClasses,
)
async def get_lti_canvas_classes(class_id: str, request: StateRequest):
    lti_classes = await models.LTIClass.get_by_class_id(
        request.state["db"], int(class_id)
    )

    lti_classes_results: list[schemas.LTIClass] = []

    for lti_class in lti_classes:
        lti_class_from_schema = schemas.LTIClass.model_validate(lti_class)
        lti_class_from_schema.client_id = lti_class.registration.client_id
        lti_class_from_schema.canvas_account_name = (
            lti_class.registration.canvas_account_name
        )
        lti_classes_results.append(lti_class_from_schema)

    return {"classes": lti_classes_results}


@v1.post(
    "/class/{class_id}/lti/classes/{lti_class_id}/sync",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def sync_lti_class_roster(
    class_id: str, lti_class_id: str, request: StateRequest, tasks: BackgroundTasks
):
    class_id_int = int(class_id)
    lti_class = await models.LTIClass.get_by_id(request.state["db"], int(lti_class_id))
    if not lti_class:
        raise HTTPException(status_code=404, detail="LTI class not found")
    if lti_class.class_id != class_id_int:
        raise HTTPException(
            status_code=400, detail="LTI class does not belong to the specified class"
        )

    async with ManualCanvasConnectClient(
        lti_class_id=lti_class.id, request=request, tasks=tasks
    ) as client:
        try:
            await client.sync_roster()
        except CanvasConnectWarning as e:
            raise HTTPException(
                status_code=400,
                detail=e.detail
                or "A roster sync through Canvas Connect was recently completed.",
            ) from e
        except CanvasConnectException as e:
            raise HTTPException(
                status_code=500,
                detail=e.detail
                or "Syncing your roster through Canvas Connect failed. Please try again later.",
            ) from e
        except Exception as e:
            logger.exception("sync_lti_class_roster: Exception occurred")
            raise HTTPException(
                status_code=500,
                detail="We faced an internal error while syncing with Canvas Connect.",
            ) from e

    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/lti/classes/{lti_class_id}",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_lti_class(
    class_id: str, lti_class_id: str, request: StateRequest, keep_users: bool = True
):
    class_id_int = int(class_id)
    lti_class = await models.LTIClass.get_by_id(request.state["db"], int(lti_class_id))
    if not lti_class:
        raise HTTPException(status_code=404, detail="LTI class not found")

    if lti_class.class_id != class_id_int:
        raise HTTPException(
            status_code=400, detail="LTI class does not belong to the specified class"
        )

    user_ids = await models.LTIClass.remove_lti_sync(
        request.state["db"],
        lti_class.id,
        class_id_int,
        schemas.LMSType(lti_class.lti_platform),
        keep_users=keep_users,
    )

    if user_ids:
        await delete_canvas_permissions(
            request.state["authz"], user_ids, str(class_id_int)
        )

    await models.LTIClass.delete(request.state["db"], lti_class.id)
    logger.info(
        f"Canvas LTI class {lti_class.id} unlinked from PingPong group {class_id_int} by user {request.state['session'].user.id}."
    )
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/lms/canvas/{tenant}/link",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.CanvasRedirect,
)
async def get_canvas_link(class_id: str, tenant: str, request: StateRequest):
    canvas_settings = get_canvas_config(tenant)
    async with LightweightCanvasClient(
        canvas_settings,
        int(class_id),
        request,
    ) as client:
        return {"url": client.get_oauth_link()}


@v1.post(
    "/class/{class_id}/lms/canvas/sync/dismiss",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def dismiss_canvas_sync(class_id: str, request: StateRequest):
    await models.Class.dismiss_lms_sync(request.state["db"], int(class_id))
    return {"status": "ok"}


@v1.post(
    "/class/{class_id}/lms/canvas/sync/enable",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def enable_canvas_sync(class_id: str, request: StateRequest):
    await models.Class.enable_lms_sync(request.state["db"], int(class_id))
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/lms/{lms_type}",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.LMSInstances,
)
async def get_available_lms_instances(
    class_id: str, lms_type: str, request: StateRequest
):
    return {
        "instances": [
            tenant for tenant in config.lms.lms_instances if tenant.type == lms_type
        ]
    }


@v1.get(
    "/class/{class_id}/lms/canvas/{tenant}/classes",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.LMSClasses,
)
async def get_canvas_classes(class_id: str, tenant: str, request: StateRequest):
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
                await models.Class.mark_lms_sync_error(
                    request.state["db"], int(class_id)
                )
            logger.exception("get_canvas_classes: ClientResponseError occurred")
            raise HTTPException(
                status_code=e.code, detail="Canvas returned an error: " + e.message
            ) from e
        except CanvasInvalidTokenException:
            await models.Class.mark_lms_sync_error(request.state["db"], int(class_id))
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
    "/class/{class_id}/lms/canvas/{tenant}/classes/{canvas_class_id}/verify",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def verify_canvas_class_permissions(
    class_id: str, tenant: str, canvas_class_id: str, request: StateRequest
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
                await models.Class.mark_lms_sync_error(
                    request.state["db"], int(class_id)
                )
            logger.exception(
                "verify_canvas_class_permissions: ClientResponseError occurred"
            )
            raise HTTPException(
                status_code=e.code, detail="Canvas returned an error: " + e.message
            )
        except CanvasInvalidTokenException:
            await models.Class.mark_lms_sync_error(request.state["db"], int(class_id))
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
    "/class/{class_id}/lms/canvas/{tenant}/classes/{canvas_class_id}",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def update_canvas_class(
    class_id: str, tenant: str, canvas_class_id: str, request: StateRequest
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
                await models.Class.mark_lms_sync_error(
                    request.state["db"], int(class_id)
                )
            logger.exception("update_canvas_class: ClientResponseError occurred")
            raise HTTPException(
                status_code=e.code, detail="Canvas returned an error: " + e.message
            )
        except CanvasInvalidTokenException:
            await models.Class.mark_lms_sync_error(request.state["db"], int(class_id))
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
    "/class/{class_id}/lms/canvas/{tenant}/sync",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def sync_canvas_class(
    class_id: str, tenant: str, request: StateRequest, tasks: BackgroundTasks
):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    if not class_ or not class_.lms_user_id:
        raise HTTPException(status_code=404, detail="Canvas class not linked")
    canvas_settings = get_canvas_config(tenant)
    async with ManualCanvasClient(
        canvas_settings,
        int(class_id),
        class_.lms_user_id,
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
                await models.Class.mark_lms_sync_error(
                    request.state["db"], int(class_id)
                )
            logger.exception("sync_canvas_class: ClientResponseError occurred")
            raise HTTPException(
                status_code=e.code, detail="Canvas returned an error: " + e.message
            )
        except (CanvasException, AddUserException) as e:
            if e.code == 403:
                await models.Class.mark_lms_sync_error(
                    request.state["db"], int(class_id)
                )
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
            await models.Class.mark_lms_sync_error(request.state["db"], int(class_id))
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
    "/class/{class_id}/lms/canvas/{tenant}/sync",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def unlink_canvas_class(
    class_id: str, tenant: str, request: StateRequest, keep_users: bool = True
):
    canvas_settings = get_canvas_config(tenant)
    userIds = await models.Class.remove_lms_sync(
        request.state["db"],
        int(class_id),
        canvas_settings.tenant,
        schemas.LMSType(canvas_settings.type),
        keep_users=keep_users,
    )
    await delete_canvas_permissions(request.state["authz"], userIds, class_id)
    logger.info(
        f"Canvas class unlinked from PingPong class {class_id} by user {request.state['session'].user.id}."
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/lms/canvas/{tenant}/account",
    dependencies=[Depends(Authz("can_edit_info", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def remove_canvas_connection(
    class_id: str,
    tenant: str,
    request: StateRequest,
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
                request.state["db"],
                int(class_id),
                canvas_settings.tenant,
                schemas.LMSType(canvas_settings.type),
                kill_connection=True,
                keep_users=keep_users,
            )
            await delete_canvas_permissions(request.state["authz"], userIds, class_id)
            logger.info(
                f"Canvas account removed from PingPong class {class_id} by user {request.state['session'].user.id}."
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
    request: StateRequest,
    tasks: BackgroundTasks,
    openai_client: OpenAIClient,
    opts: schemas.ActivitySummaryOpts,
):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Group not found")
    if class_.private:
        raise HTTPException(
            status_code=403,
            detail="Cannot create assistant summaries for a private class",
        )
    user = await models.User.get_by_id(
        request.state["db"], request.state["session"].user.id
    )
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
async def get_class_summary_subscription(class_id: str, request: StateRequest):
    subscribed = await models.UserClassRole.is_subscribed_to_summaries(
        request.state["db"], request.state["session"].user.id, int(class_id)
    )
    return {"subscribed": subscribed}


@v1.post(
    "/class/{class_id}/summarize/subscription",
    dependencies=[Depends(Authz("can_receive_summaries", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def subscribe_to_class_summary(class_id: str, request: StateRequest):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
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
        request.state["db"], request.state["session"].user.id, int(class_id)
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/summarize/subscription",
    dependencies=[Depends(Authz("can_receive_summaries", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def unsubscribe_from_class_summary(class_id: str, request: StateRequest):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
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
        request.state["db"], request.state["session"].user.id, int(class_id)
    )
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/supervisors",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.ClassSupervisors,
)
async def list_class_supervisors(class_id: str, request: StateRequest):
    supervisor_ids = await request.state["authz"].list_entities(
        f"class:{class_id}",
        "supervisor",
        "user",
    )
    supervisors = await models.User.get_all_by_id_if_in_class(
        request.state["db"], supervisor_ids, int(class_id)
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
    class_id: str,
    request: StateRequest,
    limit: int = 20,
    offset: int = 0,
    search: str = "",
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
        request.state["db"], int(class_id), limit=limit, offset=offset, search=search
    ):
        users.append(u)
        for role in ["admin", "teacher", "student"]:
            batch.append((f"user:{u.user_id}", role, f"class:{class_id}"))

    total, results = await asyncio.gather(
        models.Class.get_member_count(
            request.state["db"], int(class_id), search=search
        ),
        request.state["authz"].check(batch),
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
    class_id: str, data: schemas.EmailValidationRequest, request: StateRequest
):
    return await validate_email_addresses(request.state["db"], data.emails)


@v1.post(
    "/class/{class_id}/user/revalidate",
    dependencies=[Depends(Authz("can_manage_users", "class:{class_id}"))],
    response_model=schemas.EmailValidationResults,
)
async def revalidate_user_emails(
    class_id: str, data: schemas.EmailValidationResults, request: StateRequest
):
    return await revalidate_email_addresses(request.state["db"], data.results)


@v1.post(
    "/class/{class_id}/user",
    dependencies=[Depends(Authz("can_manage_users", "class:{class_id}"))],
    response_model=schemas.CreateUserResults,
)
async def add_users_to_class(
    class_id: str,
    new_ucr: schemas.CreateUserClassRoles,
    request: StateRequest,
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
    class_id: str,
    user_id: str,
    update: schemas.UpdateUserClassRole,
    request: StateRequest,
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

    existing = await models.UserClassRole.get(request.state["db"], uid, cid)
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
    await request.state["authz"].write_safe(grant=grants, revoke=revokes)

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
async def remove_user_from_class(class_id: str, user_id: str, request: StateRequest):
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
    await models.UserClassRole.delete(request.state["db"], uid, cid)

    revokes = list[Relation]()
    for role in ["admin", "teacher", "student"]:
        revokes.append((f"user:{uid}", role, f"class:{cid}"))

    await request.state["authz"].write_safe(revoke=revokes)
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/api_key/check",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.APIKeyCheck,
)
async def check_class_api_key(class_id: str, request: StateRequest):
    result = await models.Class.get_api_key(request.state["db"], int(class_id))
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
    class_id: str, update: schemas.UpdateApiKey, request: StateRequest
):
    if not update.api_key:
        raise HTTPException(
            status_code=400,
            detail="API key must be provided to update the class API key.",
        )
    existing_key = await models.Class.get_api_key(request.state["db"], int(class_id))
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
        response = await validate_api_key(
            update.api_key,
            update.provider.value,
            update.endpoint,
            update.api_version,
        )
        if not response.valid:
            raise HTTPException(
                status_code=400,
                detail="Invalid API connection information provided. Please try again.",
            )
        api_key_obj = await models.Class.update_api_key(
            request.state["db"],
            int(class_id),
            update.api_key,
            provider=update.provider,
            endpoint=update.endpoint if update.provider == "azure" else None,
            api_version=update.api_version if update.provider == "azure" else None,
            region=response.region if update.provider == "azure" else None,
            available_as_default=False,
        )
        await request.state["authz"].write_safe(
            grant=[
                (
                    f"user:{request.state['session'].user.id}",
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
async def get_class_api_key(class_id: str, request: StateRequest):
    response = None
    result = await models.Class.get_api_key(request.state["db"], int(class_id))
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
    "/models",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.AssistantModelLiteResponse,
)
async def list_model_capabilities(request: StateRequest):
    lite_models = [
        schemas.AssistantModelLite(
            id=model_id,
            supports_vision=model_data["supports_vision"],
            supports_reasoning=model_data["supports_reasoning"],
            azure_supports_vision=False,
        )
        for model_id, model_data in KNOWN_MODELS.items()
    ]
    return schemas.AssistantModelLiteResponse(models=lite_models)


@v1.get(
    "/class/{class_id}/models",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.AssistantModels,
)
async def list_class_models(
    class_id: str, request: StateRequest, openai_client: OpenAIClient
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

    filtered = [
        {
            "id": m.id,
            "created": datetime.fromtimestamp(m.created or m.created_at or 0),
            "owner": m.owned_by or "",
            "default_prompt_id": KNOWN_MODELS[m.id].get("default_prompt_id"),
            "name": KNOWN_MODELS[m.id]["name"],
            "sort_order": KNOWN_MODELS[m.id]["sort_order"],
            "type": KNOWN_MODELS[m.id]["type"],
            "description": KNOWN_MODELS[m.id]["description"],
            "is_latest": KNOWN_MODELS[m.id]["is_latest"],
            "is_new": KNOWN_MODELS[m.id]["is_new"],
            "highlight": KNOWN_MODELS[m.id]["highlight"],
            "supports_vision": KNOWN_MODELS[m.id]["supports_vision"],
            "supports_file_search": KNOWN_MODELS[m.id]["supports_file_search"],
            "supports_code_interpreter": KNOWN_MODELS[m.id][
                "supports_code_interpreter"
            ],
            "supports_classic_assistants": KNOWN_MODELS[m.id][
                "supports_classic_assistants"
            ],
            "supports_next_gen_assistants": KNOWN_MODELS[m.id][
                "supports_next_gen_assistants"
            ],
            "supports_minimal_reasoning_effort": KNOWN_MODELS[m.id][
                "supports_minimal_reasoning_effort"
            ],
            "supports_none_reasoning_effort": KNOWN_MODELS[m.id][
                "supports_none_reasoning_effort"
            ],
            "supports_verbosity": KNOWN_MODELS[m.id]["supports_verbosity"],
            "supports_web_search": KNOWN_MODELS[m.id]["supports_web_search"],
            "supports_mcp_server": KNOWN_MODELS[m.id]["supports_mcp_server"],
            "supports_temperature": KNOWN_MODELS[m.id]["supports_temperature"],
            "supports_reasoning": KNOWN_MODELS[m.id]["supports_reasoning"],
            "reasoning_effort_levels": KNOWN_MODELS[m.id].get(
                "reasoning_effort_levels"
            ),
        }
        for m in all_models.data
        if m.id in KNOWN_MODELS.keys()
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
                "sort_order": 4.1,
                "type": "chat",
                "is_new": False,
                "highlight": False,
                "is_latest": True,
                "supports_vision": True,
                "supports_file_search": True,
                "supports_code_interpreter": True,
                "supports_temperature": True,
                "supports_reasoning": False,
                "supports_classic_assistants": True,
                "supports_next_gen_assistants": False,
                "supports_minimal_reasoning_effort": False,
                "supports_none_reasoning_effort": False,
                "supports_verbosity": False,
                "supports_web_search": False,
                "supports_mcp_server": False,
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
                "sort_order": 4.2,
                "type": "chat",
                "is_new": False,
                "highlight": False,
                "is_latest": True,
                "supports_vision": False,
                "supports_file_search": True,
                "supports_code_interpreter": True,
                "supports_temperature": True,
                "supports_reasoning": False,
                "supports_classic_assistants": True,
                "supports_next_gen_assistants": False,
                "supports_minimal_reasoning_effort": False,
                "supports_none_reasoning_effort": False,
                "supports_verbosity": False,
                "supports_web_search": False,
                "supports_mcp_server": False,
                "description": "The latest GPT-4 Turbo preview model.",
            }
        )

    if not (
        await request.state["authz"].check(
            [
                (
                    f"user:{request.state['session'].user.id}",
                    "admin",
                    f"class:{class_id}",
                ),
            ]
        )
    )[0]:
        for model in filtered:
            model["hide_in_model_selector"] = (
                True
                if model["id"] in ADMIN_ONLY_MODELS
                else model.get("hide_in_model_selector")
            )

    for model in filtered:
        model["hide_in_model_selector"] = (
            True
            if model["id"] in HIDDEN_MODELS
            else model.get("hide_in_model_selector")
        )

    if isinstance(openai_client, openai.AsyncAzureOpenAI):
        filtered = [m for m in filtered if m["id"] not in AZURE_UNAVAILABLE_MODELS]

    # Vision is not supported in Azure, set vision_support_override to False
    if isinstance(openai_client, openai.AsyncAzureOpenAI):
        for model in filtered:
            model["vision_support_override"] = (
                False if model["supports_vision"] else None
            )

    filtered.sort(key=lambda x: x["sort_order"])

    default_prompt_ids = set(model.get("default_prompt_id") for model in filtered)
    default_prompts = [
        DEFAULT_PROMPTS.get(prompt_id)
        for prompt_id in default_prompt_ids
        if prompt_id in DEFAULT_PROMPTS
    ]

    return {
        "models": filtered,
        "default_prompts": default_prompts,
        "enforce_classic_assistants": isinstance(
            openai_client, openai.AsyncAzureOpenAI
        ),
    }


@v1.websocket(
    "/class/{class_id}/thread/{thread_id}/audio",
)
async def audio_stream(
    websocket: StateWebSocket,
    class_id: str,
    thread_id: str,
    share_token: str | None = None,
    session_token: str | None = None,
):
    websocket.state["anonymous_share_token"] = share_token
    websocket.state["anonymous_session_token"] = session_token
    await browser_realtime_websocket(websocket, class_id, thread_id)


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
    class_id: str, thread_id: str, request: StateRequest, openai_client: OpenAIClient
):
    thread = await models.Thread.get_by_id_with_users_voice_mode(
        request.state["db"], int(thread_id)
    )
    if thread.version <= 2:
        (
            messages,
            [assistant, file_names, all_files],
            is_supervisor_check,
            runs_result,
        ) = await asyncio.gather(
            openai_client.beta.threads.messages.list(
                thread.thread_id, limit=20, order="desc"
            ),
            models.Thread.get_thread_components(request.state["db"], thread.id),
            request.state["authz"].check(
                [
                    (
                        f"user:{request.state['session'].user.id}",
                        "supervisor",
                        f"class:{class_id}",
                    ),
                ]
            ),
            openai_client.beta.threads.runs.list(
                thread.thread_id, limit=1, order="desc"
            ),
        )
        messages.data = [
            schemas.ThreadMessage.model_validate(message.model_dump())
            for message in messages.data
        ]
        last_run = [r async for r in runs_result]
        current_user_ids = [
            request.state["session"].user.id
        ] + await models.User.get_previous_ids_by_id(
            request.state["db"], request.state["session"].user.id
        )
        if messages.data:
            users = {str(u.id): u for u in thread.users}

        is_supervisor = is_supervisor_check[0]
        is_current_user = False
        for message in messages.data:
            for content in message.content:
                if content.type == "text" and content.text.annotations:
                    for annotation in content.text.annotations:
                        if (
                            annotation.type == "file_citation"
                            and annotation.file_citation
                        ):
                            annotation.file_citation.file_name = file_names.get(
                                annotation.file_citation.file_id, "Unknown citation"
                            )
            user_id = message.metadata.pop("user_id", None)
            if not user_id:
                continue
            if int(user_id) in current_user_ids:
                is_current_user = True
                message.metadata["is_current_user"] = True
            else:
                message.metadata["is_current_user"] = False
            if user_id not in users:
                if is_current_user:
                    message.metadata["name"] = "Me"
                else:
                    message.metadata["name"] = "Unknown User"
            else:
                message.metadata["name"] = (
                    name(users[user_id])
                    if thread.display_user_info and is_supervisor
                    else "Anonymous User"
                    if thread.private
                    else pseudonym(thread, users[user_id])
                )
        placeholder_ci_calls = []
        if "code_interpreter" in thread.tools_available and messages.data:
            placeholder_ci_calls = await get_placeholder_ci_calls(
                request.state["db"],
                messages.data[0].assistant_id
                if messages.data[0].assistant_id
                else "None",
                thread.thread_id,
                thread.id,
                messages.data[-1].created_at,
            )

        if assistant:
            thread.assistant_names = {assistant.id: assistant.name}
        else:
            thread.assistant_names = {0: "Deleted Assistant"}
        thread.user_names = user_names(
            thread, request.state["session"].user.id, is_supervisor
        )

        can_view_prompt = False
        if thread.instructions and assistant:
            if not assistant.hide_prompt:
                can_view_prompt = True
            else:
                can_view_prompt = await request.state["authz"].test(
                    f"user:{request.state['session'].user.id}",
                    "can_edit",
                    f"assistant:{assistant.id}",
                )

        return {
            "thread": thread,
            "model": assistant.model if assistant else "None",
            "tools_available": thread.tools_available,
            "run": last_run[0] if last_run else None,
            "messages": list(messages.data),
            "limit": 20,
            "ci_messages": placeholder_ci_calls,
            "fs_messages": [],
            "ws_messages": [],
            "mcp_messages": [],
            "reasoning_messages": [],
            "attachments": all_files,
            "instructions": thread.instructions if can_view_prompt else None,
            "recording": thread.voice_mode_recording
            if is_supervisor or is_current_user
            else None,
            "has_more": messages.has_more,
        }
    elif thread.version == 3:
        limit = 20
        run_limit = max(1, ceil(limit / 2))
        run_ids, has_more_runs = await models.Run.get_run_window(
            request.state["db"],
            thread.id,
            run_limit,
            order="desc",
        )

        (
            [messages_v3, tool_calls_v3, reasoning_steps_v3],
            latest_run,
            [assistant, file_names, all_files],
            is_supervisor_check,
        ) = await asyncio.gather(
            models.Thread.list_messages_tool_calls(
                request.state["db"],
                thread.id,
                run_ids=run_ids,
                order="desc",
            ),
            models.Thread.get_latest_run_by_thread_id(request.state["db"], thread.id),
            models.Thread.get_thread_components(request.state["db"], thread.id),
            request.state["authz"].check(
                [
                    (
                        f"user:{request.state['session'].user.id}",
                        "supervisor",
                        f"class:{class_id}",
                    ),
                ]
            ),
        )
        current_user_ids = [
            request.state["session"].user.id
        ] + await models.User.get_previous_ids_by_id(
            request.state["db"], request.state["session"].user.id
        )
        users = {str(u.id): u for u in thread.users}

        is_supervisor = is_supervisor_check[0]
        is_current_user = False
        show_reasoning_summaries = is_supervisor or (
            assistant and not assistant.hide_reasoning_summaries
        )
        show_file_search_queries = is_supervisor or (
            assistant and not assistant.hide_file_search_queries
        )
        show_file_search_result_quotes = is_supervisor or (
            assistant and not assistant.hide_file_search_result_quotes
        )
        show_file_search_document_names = is_supervisor or (
            assistant and not assistant.hide_file_search_document_names
        )
        show_web_search_sources = is_supervisor or (
            assistant and not assistant.hide_web_search_sources
        )
        show_web_search_actions = is_supervisor or (
            assistant and not assistant.hide_web_search_actions
        )
        show_mcp_server_call_details = is_supervisor or (
            assistant and not assistant.hide_mcp_server_call_details
        )

        thread_messages: list[schemas.ThreadMessage] = []
        placeholder_ci_calls = []
        file_search_calls: list[schemas.FileSearchMessage] = []
        file_search_results: dict[str, schemas.FileSearchToolAnnotationResult] = {}
        web_search_calls: list[schemas.WebSearchMessage] = []
        mcp_messages: list[schemas.MCPMessage] = []
        reasoning_messages: list[schemas.ReasoningMessage] = []
        for tool_call in tool_calls_v3:
            if tool_call.type == schemas.ToolCallType.CODE_INTERPRETER:
                tool_content: list[schemas.CodeInterpreterMessageContent] = []

                if tool_call.code:
                    tool_content.append(
                        schemas.MessageContentCode(code=tool_call.code, type="code")
                    )

                for output in tool_call.outputs:
                    if output.output_type == schemas.CodeInterpreterOutputType.IMAGE:
                        tool_content.append(
                            schemas.MessageContentCodeOutputImageURL(
                                url=output.url, type="code_output_image_url"
                            )
                        )
                    elif output.output_type == schemas.CodeInterpreterOutputType.LOGS:
                        tool_content.append(
                            schemas.MessageContentCodeOutputLogs(
                                logs=output.logs, type="code_output_logs"
                            )
                        )

                placeholder_ci_calls.append(
                    schemas.CodeInterpreterMessage(
                        id=str(tool_call.id),
                        assistant_id=str(assistant.id) if assistant else "",
                        created_at=tool_call.created.timestamp(),
                        content=tool_content,
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        message_type="code_interpreter_call",
                        output_index=tool_call.output_index,
                    )
                )
            elif tool_call.type == schemas.ToolCallType.FILE_SEARCH:
                for result in tool_call.results:
                    if file_search_results.get(result.file_id):
                        file_search_results[result.file_id].text += (
                            "\n\n <hr/> \n\n" + result.text
                        )
                    else:
                        file_search_results[result.file_id] = (
                            schemas.FileSearchToolAnnotationResult(
                                file_id=result.file_id,
                                filename=result.filename,
                                text=result.text,
                            )
                        )
                file_search_calls.append(
                    schemas.FileSearchMessage(
                        id=str(tool_call.id),
                        assistant_id=str(assistant.id)
                        if assistant and assistant.id
                        else "",
                        created_at=tool_call.created.timestamp(),
                        content=[
                            schemas.FileSearchCall(
                                step_id=str(tool_call.id),
                                type="file_search_call",
                                status=tool_call.status.value,
                                queries=json.loads(tool_call.queries)
                                if tool_call.queries and show_file_search_queries
                                else [],
                            )
                        ],
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        message_type="file_search_call",
                        output_index=tool_call.output_index,
                    )
                )
            elif tool_call.type == schemas.ToolCallType.WEB_SEARCH:
                action = (
                    tool_call.web_search_actions[0]
                    if tool_call.web_search_actions and show_web_search_actions
                    else None
                )

                if not action or not action.type:
                    action_obj = None
                else:
                    match action.type:
                        case schemas.WebSearchActionType.SEARCH:
                            sources = (
                                [
                                    ActionSearchSource(url=source.url or "", type="url")
                                    for source in action.sources
                                ]
                                if action and action.sources and show_web_search_sources
                                else []
                            )
                            action_obj = ActionSearch(
                                query=action.query or "",
                                type="search",
                                sources=sources,
                            )
                        case schemas.WebSearchActionType.FIND:
                            action_obj = ActionFind(
                                url=action.url or "",
                                pattern=action.pattern or "",
                                type="find",
                            )
                        case schemas.WebSearchActionType.OPEN_PAGE:
                            action_obj = ActionOpenPage(
                                url=action.url or "",
                                type="open_page",
                            )
                        case _:
                            action_obj = None

                web_search_calls.append(
                    schemas.WebSearchMessage(
                        id=str(tool_call.id),
                        assistant_id=str(thread.assistant_id)
                        if thread.assistant_id
                        else "",
                        created_at=tool_call.created.timestamp(),
                        content=[
                            schemas.WebSearchCall(
                                step_id=str(tool_call.id),
                                type="web_search_call",
                                status=tool_call.status.value,
                                action=action_obj,
                            )
                        ],
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        output_index=tool_call.output_index,
                        message_type="web_search_call",
                    )
                )
            elif tool_call.type == schemas.ToolCallType.MCP_SERVER:
                parsed_error: dict[str, Any] | str | None = None
                if tool_call.error and show_mcp_server_call_details:
                    try:
                        parsed_error = json.loads(tool_call.error)
                    except json.JSONDecodeError:
                        parsed_error = tool_call.error

                mcp_server = tool_call.mcp_server_tool
                mcp_messages.append(
                    schemas.MCPMessage(
                        id=str(tool_call.id),
                        assistant_id=str(assistant.id) if assistant else "",
                        created_at=tool_call.created.timestamp(),
                        content=[
                            schemas.MCPServerCall(
                                step_id=str(tool_call.id),
                                type="mcp_server_call",
                                server_label=mcp_server.server_label
                                if mcp_server
                                else "",
                                server_name=mcp_server.display_name
                                if mcp_server
                                else None,
                                tool_name=tool_call.mcp_tool_name,
                                arguments=tool_call.mcp_arguments
                                if show_mcp_server_call_details
                                else None,
                                output=tool_call.mcp_output
                                if show_mcp_server_call_details
                                else None,
                                error=parsed_error,
                                status=tool_call.status.value,
                            )
                        ],
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        message_type="mcp_server_call",
                        output_index=tool_call.output_index,
                    )
                )
            elif tool_call.type == schemas.ToolCallType.MCP_LIST_TOOLS:
                parsed_error_list_tools: dict[str, Any] | str | None = None
                if tool_call.error and show_mcp_server_call_details:
                    try:
                        parsed_error_list_tools = json.loads(tool_call.error)
                    except json.JSONDecodeError:
                        parsed_error_list_tools = tool_call.error

                mcp_tools: list[schemas.MCPListToolsTool] = []
                if show_mcp_server_call_details:
                    for tool in tool_call.mcp_tools_listed:
                        try:
                            input_schema = (
                                json.loads(tool.input_schema)
                                if tool.input_schema
                                else None
                            )
                        except json.JSONDecodeError:
                            input_schema = None
                        try:
                            annotations = (
                                json.loads(tool.annotations)
                                if tool.annotations
                                else None
                            )
                        except json.JSONDecodeError:
                            annotations = None

                        mcp_tools.append(
                            schemas.MCPListToolsTool(
                                name=tool.name,
                                description=tool.description,
                                input_schema=input_schema,
                                annotations=annotations,
                            )
                        )

                mcp_server = tool_call.mcp_server_tool
                mcp_messages.append(
                    schemas.MCPMessage(
                        id=str(tool_call.id),
                        assistant_id=str(assistant.id) if assistant else "",
                        created_at=tool_call.created.timestamp(),
                        content=[
                            schemas.MCPListToolsCall(
                                step_id=str(tool_call.id),
                                type="mcp_list_tools_call",
                                server_label=mcp_server.server_label
                                if mcp_server
                                else "",
                                server_name=mcp_server.display_name
                                if mcp_server
                                else None,
                                tools=mcp_tools,
                                error=parsed_error_list_tools,
                                status=tool_call.status.value,
                            )
                        ],
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        message_type="mcp_list_tools_call",
                        output_index=tool_call.output_index,
                    )
                )

        for reasoning_step in reasoning_steps_v3:
            reasoning_messages.append(
                schemas.ReasoningMessage(
                    id=str(reasoning_step.id),
                    assistant_id=str(assistant.id)
                    if assistant and assistant.id
                    else "",
                    created_at=reasoning_step.created.timestamp(),
                    content=[
                        schemas.ReasoningCall(
                            step_id=reasoning_step.reasoning_id
                            or str(reasoning_step.id),
                            type="reasoning",
                            summary=[
                                schemas.ReasoningSummaryPart(
                                    id=part.id,
                                    summary_text=part.summary_text,
                                    part_index=part.part_index,
                                )
                                for part in (
                                    reasoning_step.summary_parts
                                    if show_reasoning_summaries
                                    else []
                                )
                            ],
                            status=reasoning_step.status,
                            thought_for=reasoning_step.thought_for,
                        )
                    ],
                    metadata={},
                    object="thread.message",
                    message_type="reasoning",
                    role="assistant",
                    run_id=str(reasoning_step.run_id),
                    thread_id=str(thread.id),
                    output_index=reasoning_step.output_index,
                )
            )

        allowed_message_ids = allowed_assistant_message_ids(
            messages_v3, tool_calls_v3, reasoning_steps_v3
        )

        messages_v3.reverse()
        for message in messages_v3:
            if message.role == "assistant" and message.id not in allowed_message_ids:
                logger.info(
                    "RESPONSES_MULTI_MESSAGE_THREAD_SKIP: Skipping consecutive assistant message with run_id %s",
                    message.run_id,
                )
                continue
            _message = schemas.ThreadMessage(
                id=str(message.id),
                thread_id=str(thread.id),
                assistant_id=str(assistant.id) if assistant and assistant.id else None,
                created_at=message.created.timestamp(),
                object="thread.message",
                role=message.role.value,
                content=[],
                status=message.message_status.value
                if message.message_status != "pending"
                else "in_progress",
                run_id=str(message.run_id) if message.run_id else None,
                output_index=message.output_index,
            )
            attachments: list[Attachment] = []
            attachments_dict: dict[str, list[dict[str, str]]] = {}
            for attachment in message.file_search_attachments:
                attachments_dict.setdefault(attachment.file_id, []).append(
                    {"type": "file_search"}
                )

            for attachment in message.code_interpreter_attachments:
                attachments_dict.setdefault(attachment.file_id, []).append(
                    {"type": "code_interpreter"}
                )
            for file_id, tools in attachments_dict.items():
                attachments.append({"file_id": file_id, "tools": tools})

            _message.attachments = attachments
            for content in message.content:
                match content.type:
                    case schemas.MessagePartType.INPUT_TEXT:
                        _message.content.append(
                            schemas.ThreadTextContentBlock(
                                text=schemas.ThreadText(
                                    value=content.text, annotations=[]
                                ),
                                type="text",
                            )
                        )
                    case schemas.MessagePartType.INPUT_IMAGE:
                        _message.content.append(
                            ImageFileContentBlock(
                                type="image_file",
                                image_file=ImageFile(
                                    file_id=content.input_image_file_id,
                                ),
                            )
                        )
                    case schemas.MessagePartType.OUTPUT_TEXT:
                        _annotations: list[schemas.ThreadAnnotation] = []
                        _file_ids_file_citation_annotation: set[str] = set()
                        if content.annotations:
                            for annotation in content.annotations:
                                if (
                                    annotation.type
                                    == schemas.AnnotationType.FILE_CITATION
                                    and show_file_search_document_names
                                ):
                                    _file_record = file_search_results.get(
                                        annotation.file_id
                                    )
                                    if _file_record:
                                        if (
                                            annotation.file_id
                                            not in _file_ids_file_citation_annotation
                                        ):
                                            _file_ids_file_citation_annotation.add(
                                                annotation.file_id
                                            )
                                            _file_citation = FileCitationAnnotation(
                                                end_index=annotation.end_index or 0,
                                                start_index=annotation.start_index or 0,
                                                file_citation=FileCitation(
                                                    file_id=_file_record.file_id,
                                                    file_name=_file_record.filename,
                                                    quote=_file_record.text
                                                    if show_file_search_result_quotes
                                                    else "",
                                                ),
                                                text="responses_v3",
                                                type="file_citation",
                                            )
                                            _annotations.append(_file_citation)
                                elif (
                                    annotation.type == schemas.AnnotationType.FILE_PATH
                                    or (
                                        annotation.type
                                        == schemas.AnnotationType.CONTAINER_FILE_CITATION
                                        and not annotation.vision_file_id
                                    )
                                ):
                                    _annotations.append(
                                        FilePathAnnotation(
                                            type="file_path",
                                            end_index=annotation.end_index,
                                            start_index=annotation.start_index,
                                            file_path=FilePath(
                                                file_id=str(
                                                    annotation.file_object_id
                                                    or annotation.file_id
                                                ),
                                            ),
                                            text=annotation.text or "",
                                        )
                                    )
                                elif (
                                    annotation.type
                                    == schemas.AnnotationType.CONTAINER_FILE_CITATION
                                    and annotation.vision_file_id
                                ):
                                    _message.content.insert(
                                        0,
                                        ImageFileContentBlock(
                                            image_file=ImageFile(
                                                file_id=annotation.vision_file_id,
                                            ),
                                            type="image_file",
                                        ),
                                    )
                                elif (
                                    annotation.type
                                    == schemas.AnnotationType.URL_CITATION
                                ):
                                    _annotations.append(
                                        AnnotationURLCitation(
                                            type="url_citation",
                                            end_index=annotation.end_index or 0,
                                            start_index=annotation.start_index or 0,
                                            url=annotation.url or "",
                                            title=annotation.title or "",
                                            text=annotation.text or "",
                                        )
                                    )

                        _message.content.append(
                            schemas.ThreadTextContentBlock(
                                type="text",
                                text=schemas.ThreadText(
                                    value=content.text,
                                    annotations=_annotations,
                                ),
                            )
                        )

            if not message.user_id:
                thread_messages.append(_message)
                continue

            if int(message.user_id) in current_user_ids:
                is_current_user = True
                _message.metadata = {"is_current_user": True}
            else:
                _message.metadata = {"is_current_user": False}

            if str(message.user_id) not in users:
                if is_current_user:
                    _message.metadata["name"] = "Me"
                else:
                    _message.metadata["name"] = "Unknown User"
            else:
                _message.metadata["name"] = (
                    name(users[str(message.user_id)])
                    if thread.display_user_info and is_supervisor
                    else "Anonymous User"
                    if thread.private
                    else pseudonym(thread, users[str(message.user_id)])
                )
            thread_messages.append(_message)

        if assistant:
            thread.assistant_names = {assistant.id: assistant.name}
        else:
            thread.assistant_names = {0: "Deleted Assistant"}
        thread.user_names = user_names(
            thread, request.state["session"].user.id, is_supervisor
        )

        can_view_prompt = False
        if thread.instructions and assistant:
            if not assistant.hide_prompt:
                can_view_prompt = True
            else:
                can_view_prompt = await request.state["authz"].test(
                    f"user:{request.state['session'].user.id}",
                    "can_edit",
                    f"assistant:{assistant.id}",
                )

        if latest_run:
            last_run_db = schemas.OpenAIRun(
                id=str(latest_run.run_id),
                assistant_id=str(thread.assistant_id),
                created_at=int(latest_run.created.timestamp()),
                completed_at=(
                    int(latest_run.completed.timestamp())
                    if latest_run.completed
                    else None
                ),
                cancelled_at=None,
                expires_at=None,
                failed_at=None,
                status=latest_run.status.value,
                thread_id=str(thread_id),
                instructions=thread.instructions or "",
                last_error=schemas.OpenAIRunError(
                    message=latest_run.error_message,
                    code=latest_run.error_code,
                )
                if latest_run.error_message
                else None,
                metadata={},
                model=assistant.model if assistant else "None",
                object="thread.run",
                tools=[],
            )
        return {
            "thread": thread,
            "model": assistant.model if assistant else "None",
            "tools_available": thread.tools_available,
            "run": last_run_db if latest_run else None,
            "messages": thread_messages,
            "limit": 20,
            "ci_messages": placeholder_ci_calls,
            "fs_messages": file_search_calls,
            "ws_messages": web_search_calls,
            "mcp_messages": mcp_messages,
            "reasoning_messages": reasoning_messages,
            "attachments": all_files,
            "instructions": thread.instructions if can_view_prompt else None,
            "lecture_video_id": thread.lecture_video_id,
            "recording": thread.voice_mode_recording
            if is_supervisor or is_current_user
            else None,
            "has_more": has_more_runs,
        }
    else:
        raise HTTPException(status_code=400, detail="Invalid thread version")


@v1.get(
    "/class/{class_id}/thread/{thread_id}/recording",
    dependencies=[
        Depends(
            Authz("can_view", "thread:{thread_id}"),
        )
    ],
    response_class=StreamingResponse,
)
async def get_thread_recording(
    class_id: str,
    thread_id: str,
    request: StateRequest,
):
    user_id = request.state["session"].user.id
    thread, is_supervisor_check = await asyncio.gather(
        models.Thread.get_by_id_with_users_voice_mode(
            request.state["db"], int(thread_id)
        ),
        request.state["authz"].check(
            [
                (
                    f"user:{user_id}",
                    "supervisor",
                    f"class:{class_id}",
                ),
            ]
        ),
    )

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    if not thread.voice_mode_recording:
        raise HTTPException(
            status_code=404,
            detail="This thread does not have a recording.",
        )
    is_participant = user_id in [u.id for u in thread.users]
    if not (is_supervisor_check[0] or is_participant):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view this recording.",
        )

    async def _prefetch_stream(gen):
        it = gen.__aiter__()
        try:
            first = await it.__anext__()
        except StopAsyncIteration:

            async def _empty():
                if False:
                    yield b""

            return _empty()
        except AudioStoreError:
            raise

        async def _wrapped():
            yield first
            try:
                async for chunk in it:
                    yield chunk
            except AudioStoreError:
                logger.info(
                    "AudioStoreError while streaming recording; aborting stream."
                )
                return
            except Exception:
                logger.exception("Unexpected error while streaming recording")
                return

        return _wrapped()

    try:
        stream = await _prefetch_stream(
            config.audio_store.store.get_file(thread.voice_mode_recording.recording_id)
        )
        return StreamingResponse(
            stream,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{thread.voice_mode_recording}"'
            },
        )
    except AudioStoreError:
        raise HTTPException(
            status_code=400,
            detail="Unable to retrieve the recording. It may not exist or has been deleted.",
        )
    except Exception:
        logger.exception("get_thread_recording: Exception occurred")
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while retrieving the recording.",
        )


@v1.post(
    "/class/{class_id}/thread/{thread_id}/recording/transcribe",
    dependencies=[
        Depends(
            Authz("can_view", "thread:{thread_id}"),
        )
    ],
    response_model=schemas.GenericStatus,
)
async def transcribe_thread_recording(
    class_id: str,
    thread_id: str,
    request: StateRequest,
    tasks: BackgroundTasks,
    openai_client: OpenAIClient,
):
    user_id = request.state["session"].user.id
    thread, is_supervisor_check = await asyncio.gather(
        models.Thread.get_by_id_with_users_voice_mode(
            request.state["db"], int(thread_id)
        ),
        request.state["authz"].check(
            [
                (
                    f"user:{user_id}",
                    "supervisor",
                    f"class:{class_id}",
                ),
            ]
        ),
    )

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    if not thread.voice_mode_recording:
        raise HTTPException(
            status_code=404,
            detail="This thread does not have a recording.",
        )
    is_participant = user_id in [u.id for u in thread.users]
    if not (is_supervisor_check[0] or is_participant):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to transcribe this recording.",
        )

    tasks.add_task(
        safe_task,
        transcribe_thread_recording_and_email_link,
        openai_client,
        class_id,
        thread_id,
        user_id,
    )
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/thread/{thread_id}/recording/transcribe/download",
    dependencies=[
        Depends(
            Authz("can_view", "thread:{thread_id}"),
        )
    ],
)
async def redirect_to_transcription_download(
    class_id: str,
    thread_id: str,
    request: StateRequest,
):
    token = request.query_params.get("token")
    nowfn = get_now_fn(request)
    try:
        auth_token = decode_auth_token(token, nowfn=nowfn)
        sub_data = json.loads(auth_token.sub)
        requestor_user_id = sub_data["user_id"]
        download_name = sub_data["download_name"]
        if requestor_user_id != request.state["session"].user.id:
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
    except ArtifactStoreError:
        return RedirectResponse(
            config.url(f"/group/{class_id}/manage?error_code=9"),
            status_code=303,
        )
    except (jwt.exceptions.PyJWTError, Exception):
        return RedirectResponse(
            config.url(f"/group/{class_id}/manage?error_code=6"),
            status_code=303,
        )


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
    request: StateRequest,
    openai_client: OpenAIClient,
    run_id: str,
    step_id: str,
):
    thread = await models.Thread.get_by_id(request.state["db"], int(thread_id))
    if thread.version <= 2:
        messages = await get_ci_messages_from_step(
            openai_client, thread.thread_id, run_id, step_id
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid thread version")
    return {
        "ci_messages": messages,
    }


@v1.get(
    "/class/{class_id}/export",
    dependencies=[Depends(Authz("supervisor", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def export_class_threads(
    class_id: str,
    request: StateRequest,
    tasks: BackgroundTasks,
    openai_client: OpenAIClient,
):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
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
        request.state["session"].user.id,
    )
    return {"status": "ok"}


@v1.post(
    "/class/{class_id}/copy",
    dependencies=[Depends(Authz("admin") | ClassInstitutionAdmin())],
    response_model=schemas.GenericStatus,
)
async def copy_class(
    class_id: str,
    copy_options: schemas.CopyClassRequest,
    request: StateRequest,
    tasks: BackgroundTasks,
    openai_client: OpenAIClient,
):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Class not found")

    target_institution_id = copy_options.institution_id or class_.institution_id
    can_create_class = await request.state["authz"].test(
        request.state["auth_user"],
        "can_create_class",
        f"institution:{target_institution_id}",
    )
    if not can_create_class:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to create a class in the target institution.",
        )

    copy_options.institution_id = target_institution_id
    if (
        copy_options.copy_assistants == "all"
        and copy_options.copy_users == "moderators"
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot copy only moderators when copying all assistants.",
        )
    tasks.add_task(
        safe_task,
        copy_group,
        copy_options,
        openai_client,
        class_id,
        request.state["session"].user.id,
    )
    return {"status": "ok"}


@v1.post(
    "/admin/migrate/assistants/model",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def migrate_models(
    req: schemas.AssistantModelUpgradeRequest,
    request: StateRequest,
    tasks: BackgroundTasks,
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
    request: StateRequest,
    tasks: BackgroundTasks,
):
    tasks.add_task(
        safe_task,
        export_threads_multiple_classes,
        data.class_ids,
        request.state["session"].user.id,
        data.include_user_emails,
        data.user_ids,
        data.user_emails,
    )
    return {"status": "ok"}


@v1.get(
    "/admin/{class_id}/lms",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.ClassLMSInfo,
)
async def get_class_lms_data(class_id: str, request: StateRequest):
    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    if not class_:
        raise HTTPException(status_code=404, detail="Class not found")

    return class_


@v1.get(
    "/class/{class_id}/export/download",
    dependencies=[Depends(Authz("supervisor", "class:{class_id}"))],
)
async def redirect_to_export(class_id: str, request: StateRequest):
    token = request.query_params.get("token")
    nowfn = get_now_fn(request)
    try:
        auth_token = decode_auth_token(token, nowfn=nowfn)
        sub_data = json.loads(auth_token.sub)
        requestor_user_id = sub_data["user_id"]
        download_name = sub_data["download_name"]
        if requestor_user_id != request.state["session"].user.id:
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
    except ArtifactStoreError:
        return RedirectResponse(
            config.url(f"/group/{class_id}/manage?error_code=9"),
            status_code=303,
        )
    except (jwt.exceptions.PyJWTError, Exception):
        return RedirectResponse(
            config.url(f"/group/{class_id}/manage?error_code=6"),
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
    request: StateRequest,
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

    thread = await models.Thread.get_by_id_with_users(
        request.state["db"], int(thread_id)
    )
    if thread.version <= 2:
        messages_task = openai_client.beta.threads.messages.list(
            thread.thread_id, limit=limit, order="asc", before=before
        )
        file_names_task = models.Thread.get_file_search_files(
            request.state["db"], thread.id
        )
        is_supervisor_check_task = request.state["authz"].check(
            [
                (
                    f"user:{request.state['session'].user.id}",
                    "supervisor",
                    f"class:{class_id}",
                ),
            ]
        )

        messages, file_names, is_supervisor_check = await asyncio.gather(
            messages_task,
            file_names_task,
            is_supervisor_check_task,
        )

        messages.data = [
            schemas.ThreadMessage.model_validate(message.model_dump())
            for message in messages.data
        ]

        current_user_ids = [
            request.state["session"].user.id
        ] + await models.User.get_previous_ids_by_id(
            request.state["db"], request.state["session"].user.id
        )
        if messages.data:
            users = {u.id: u.created for u in thread.users}

        is_supervisor = is_supervisor_check[0]
        is_current_user = False
        for message in messages.data:
            for content in message.content:
                if content.type == "text" and content.text.annotations:
                    for annotation in content.text.annotations:
                        if (
                            annotation.type == "file_citation"
                            and annotation.file_citation
                        ):
                            annotation.file_citation.file_name = file_names.get(
                                annotation.file_citation.file_id, "Unknown citation"
                            )
            user_id = message.metadata.pop("user_id", None)
            if not user_id:
                continue
            if int(user_id) in current_user_ids:
                is_current_user = True
                message.metadata["is_current_user"] = True
            else:
                message.metadata["is_current_user"] = False
            if user_id not in users:
                if is_current_user:
                    message.metadata["name"] = "Me"
                else:
                    message.metadata["name"] = "Unknown User"
            else:
                message.metadata["name"] = (
                    name(users[user_id])
                    if thread.display_user_info and is_supervisor_check[0]
                    else "Anonymous User"
                    if thread.private
                    else pseudonym(thread, users[user_id])
                )

        placeholder_ci_calls = []
        # Only run the extra steps if code_interpreter is available
        if "code_interpreter" in thread.tools_available and messages.data:
            placeholder_ci_calls = await get_placeholder_ci_calls(
                request.state["db"],
                messages.data[0].assistant_id
                if messages.data[0].assistant_id
                else "None",
                thread.thread_id,
                thread.id,
                messages.data[0].created_at,
                messages.data[-1].created_at,
            )

        return {
            "messages": list(messages.data),
            "ci_messages": placeholder_ci_calls,
            "fs_messages": [],
            "ws_messages": [],
            "mcp_messages": [],
            "limit": limit,
            "has_more": messages.has_more,
        }
    elif thread.version == 3:
        run_limit = max(1, ceil(limit / 2))
        before_run_id: int | None = None
        if before is not None:
            try:
                before_run_id = int(before)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid before parameter",
                )

        run_ids, has_more_runs = await models.Run.get_run_window(
            request.state["db"],
            thread.id,
            run_limit,
            before_run_pk=before_run_id,
            order="asc",
        )

        if not run_ids:
            return {
                "messages": [],
                "ci_messages": [],
                "fs_messages": [],
                "ws_messages": [],
                "mcp_messages": [],
                "limit": limit,
                "has_more": False,
            }

        async def get_assistant(
            session: AsyncSession, id_: int | None
        ) -> list[models.Assistant]:
            if id_ is None:
                return []
            assistant = await models.Assistant.get_by_id(session, id_)
            return [assistant] if assistant else []

        (
            [messages_v3, tool_calls_v3, reasoning_steps_v3],
            assistants,
            file_names,
            is_supervisor_check,
        ) = await asyncio.gather(
            models.Thread.list_messages_tool_calls(
                request.state["db"],
                thread.id,
                run_ids=run_ids,
                order="asc",
            ),
            get_assistant(request.state["db"], thread.assistant_id),
            models.Thread.get_file_search_files(request.state["db"], thread.id),
            request.state["authz"].check(
                [
                    (
                        f"user:{request.state['session'].user.id}",
                        "supervisor",
                        f"class:{class_id}",
                    ),
                ]
            ),
        )

        current_user_ids = [
            request.state["session"].user.id
        ] + await models.User.get_previous_ids_by_id(
            request.state["db"], request.state["session"].user.id
        )
        users = {str(u.id): u for u in thread.users}

        is_supervisor = is_supervisor_check[0]
        is_current_user = False

        if assistants and len(assistants) == 1:
            assistant = assistants[0]
        else:
            assistant = None

        show_reasoning_summaries = is_supervisor or (
            assistant and not assistant.hide_reasoning_summaries
        )
        show_file_search_queries = is_supervisor or (
            assistant and not assistant.hide_file_search_queries
        )
        show_file_search_result_quotes = is_supervisor or (
            assistant and not assistant.hide_file_search_result_quotes
        )
        show_file_search_document_names = is_supervisor or (
            assistant and not assistant.hide_file_search_document_names
        )
        show_web_search_sources = is_supervisor or (
            assistant and not assistant.hide_web_search_sources
        )
        show_web_search_actions = is_supervisor or (
            assistant and not assistant.hide_web_search_actions
        )
        show_mcp_server_call_details = is_supervisor or (
            assistant and not assistant.hide_mcp_server_call_details
        )

        thread_messages: list[schemas.ThreadMessage] = []
        placeholder_ci_calls = []
        file_search_calls: list[schemas.FileSearchMessage] = []
        file_search_results: dict[str, schemas.FileSearchToolAnnotationResult] = {}
        reasoning_messages: list[schemas.ReasoningMessage] = []
        web_search_calls: list[schemas.WebSearchMessage] = []
        mcp_messages: list[schemas.MCPMessage] = []
        for tool_call in tool_calls_v3:
            if tool_call.type == schemas.ToolCallType.CODE_INTERPRETER:
                tool_content: list[schemas.CodeInterpreterMessageContent] = []

                if tool_call.code:
                    tool_content.append(
                        schemas.MessageContentCode(code=tool_call.code, type="code")
                    )

                for output in tool_call.outputs:
                    if output.output_type == schemas.CodeInterpreterOutputType.IMAGE:
                        tool_content.append(
                            schemas.MessageContentCodeOutputImageURL(
                                url=output.url, type="code_output_image_url"
                            )
                        )
                    elif output.output_type == schemas.CodeInterpreterOutputType.LOGS:
                        tool_content.append(
                            schemas.MessageContentCodeOutputLogs(
                                logs=output.logs, type="code_output_logs"
                            )
                        )

                placeholder_ci_calls.append(
                    schemas.CodeInterpreterMessage(
                        id=str(tool_call.id),
                        assistant_id=str(thread.assistant_id)
                        if thread.assistant_id
                        else "",
                        created_at=tool_call.created.timestamp(),
                        content=tool_content,
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        output_index=tool_call.output_index,
                    )
                )
            elif tool_call.type == schemas.ToolCallType.FILE_SEARCH:
                for result in tool_call.results:
                    if file_search_results.get(result.file_id):
                        file_search_results[result.file_id].text += (
                            "\n\n <hr/> \n\n" + result.text
                        )
                    else:
                        file_search_results[result.file_id] = (
                            schemas.FileSearchToolAnnotationResult(
                                file_id=result.file_id,
                                filename=result.filename,
                                text=result.text,
                            )
                        )

                file_search_calls.append(
                    schemas.FileSearchMessage(
                        id=str(tool_call.id),
                        assistant_id=str(thread.assistant_id)
                        if thread.assistant_id
                        else "",
                        created_at=tool_call.created.timestamp(),
                        content=[
                            schemas.FileSearchCall(
                                step_id=str(tool_call.id),
                                type="file_search_call",
                                status=tool_call.status.value,
                                queries=json.loads(tool_call.queries)
                                if tool_call.queries and show_file_search_queries
                                else [],
                            )
                        ],
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        message_type="file_search_call",
                        output_index=tool_call.output_index,
                    )
                )
            elif tool_call.type == schemas.ToolCallType.WEB_SEARCH:
                action = (
                    tool_call.web_search_actions[0]
                    if tool_call.web_search_actions and show_web_search_actions
                    else None
                )

                if not action or not action.type:
                    action_obj = None
                else:
                    match action.type:
                        case schemas.WebSearchActionType.SEARCH:
                            sources = (
                                [
                                    ActionSearchSource(url=source.url or "", type="url")
                                    for source in action.sources
                                ]
                                if action and action.sources and show_web_search_sources
                                else []
                            )
                            action_obj = ActionSearch(
                                query=action.query or "",
                                type="search",
                                sources=sources,
                            )
                        case schemas.WebSearchActionType.FIND:
                            action_obj = ActionFind(
                                url=action.url or "",
                                pattern=action.pattern or "",
                                type="find",
                            )
                        case schemas.WebSearchActionType.OPEN_PAGE:
                            action_obj = ActionOpenPage(
                                url=action.url or "",
                                type="open_page",
                            )
                        case _:
                            action_obj = None

                web_search_calls.append(
                    schemas.WebSearchMessage(
                        id=str(tool_call.id),
                        assistant_id=str(thread.assistant_id)
                        if thread.assistant_id
                        else "",
                        created_at=tool_call.created.timestamp(),
                        content=[
                            schemas.WebSearchCall(
                                step_id=str(tool_call.id),
                                type="web_search_call",
                                status=tool_call.status.value,
                                action=action_obj,
                            )
                        ],
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        output_index=tool_call.output_index,
                        message_type="web_search_call",
                    )
                )
            elif tool_call.type == schemas.ToolCallType.MCP_SERVER:
                parsed_error: dict[str, Any] | str | None = None
                if tool_call.error and show_mcp_server_call_details:
                    try:
                        parsed_error = json.loads(tool_call.error)
                    except json.JSONDecodeError:
                        parsed_error = tool_call.error

                mcp_server = tool_call.mcp_server_tool
                mcp_messages.append(
                    schemas.MCPMessage(
                        id=str(tool_call.id),
                        assistant_id=str(thread.assistant_id)
                        if thread.assistant_id
                        else "",
                        created_at=tool_call.created.timestamp(),
                        content=[
                            schemas.MCPServerCall(
                                step_id=str(tool_call.id),
                                type="mcp_server_call",
                                server_label=mcp_server.server_label
                                if mcp_server
                                else "",
                                server_name=mcp_server.display_name
                                if mcp_server
                                else None,
                                tool_name=tool_call.mcp_tool_name,
                                arguments=tool_call.mcp_arguments
                                if show_mcp_server_call_details
                                else None,
                                output=tool_call.mcp_output
                                if show_mcp_server_call_details
                                else None,
                                error=parsed_error,
                                status=tool_call.status.value,
                            )
                        ],
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        message_type="mcp_server_call",
                        output_index=tool_call.output_index,
                    )
                )
            elif tool_call.type == schemas.ToolCallType.MCP_LIST_TOOLS:
                parsed_error_list_tools: dict[str, Any] | str | None = None
                if tool_call.error and show_mcp_server_call_details:
                    try:
                        parsed_error_list_tools = json.loads(tool_call.error)
                    except json.JSONDecodeError:
                        parsed_error_list_tools = tool_call.error

                mcp_tools: list[schemas.MCPListToolsTool] = []
                if show_mcp_server_call_details:
                    for tool in tool_call.mcp_tools_listed:
                        try:
                            input_schema = (
                                json.loads(tool.input_schema)
                                if tool.input_schema
                                else None
                            )
                        except json.JSONDecodeError:
                            input_schema = None
                        try:
                            annotations = (
                                json.loads(tool.annotations)
                                if tool.annotations
                                else None
                            )
                        except json.JSONDecodeError:
                            annotations = None

                        mcp_tools.append(
                            schemas.MCPListToolsTool(
                                name=tool.name,
                                description=tool.description,
                                input_schema=input_schema,
                                annotations=annotations,
                            )
                        )

                mcp_server = tool_call.mcp_server_tool
                mcp_messages.append(
                    schemas.MCPMessage(
                        id=str(tool_call.id),
                        assistant_id=str(thread.assistant_id)
                        if thread.assistant_id
                        else "",
                        created_at=tool_call.created.timestamp(),
                        content=[
                            schemas.MCPListToolsCall(
                                step_id=str(tool_call.id),
                                type="mcp_list_tools_call",
                                server_label=mcp_server.server_label
                                if mcp_server
                                else "",
                                server_name=mcp_server.display_name
                                if mcp_server
                                else None,
                                tools=mcp_tools,
                                error=parsed_error_list_tools,
                                status=tool_call.status.value,
                            )
                        ],
                        metadata={},
                        object="thread.message",
                        role="assistant",
                        run_id=str(tool_call.run_id),
                        thread_id=str(thread.id),
                        message_type="mcp_list_tools_call",
                        output_index=tool_call.output_index,
                    )
                )

        for reasoning_step in reasoning_steps_v3:
            reasoning_messages.append(
                schemas.ReasoningMessage(
                    id=str(reasoning_step.id),
                    assistant_id=str(thread.assistant_id)
                    if thread.assistant_id
                    else "",
                    created_at=reasoning_step.created.timestamp(),
                    content=[
                        schemas.ReasoningCall(
                            step_id=reasoning_step.reasoning_id
                            or str(reasoning_step.id),
                            type="reasoning",
                            summary=[
                                schemas.ReasoningSummaryPart(
                                    id=part.id,
                                    summary_text=part.summary_text,
                                    part_index=part.part_index,
                                )
                                for part in (
                                    reasoning_step.summary_parts
                                    if show_reasoning_summaries
                                    else []
                                )
                            ],
                            status=reasoning_step.status,
                            thought_for=reasoning_step.thought_for,
                        )
                    ],
                    metadata={},
                    object="thread.message",
                    message_type="reasoning",
                    role="assistant",
                    run_id=str(reasoning_step.run_id),
                    thread_id=str(thread.id),
                    output_index=reasoning_step.output_index,
                )
            )

        allowed_message_ids = allowed_assistant_message_ids(
            messages_v3, tool_calls_v3, reasoning_steps_v3
        )

        for message in messages_v3:
            if message.role == "assistant" and message.id not in allowed_message_ids:
                logger.info(
                    "RESPONSES_MULTI_MESSAGE_LIST_MESSAGES_SKIP: Skipping consecutive assistant message with run_id %s",
                    message.run_id,
                )
                continue
            _message = schemas.ThreadMessage(
                id=str(message.id),
                thread_id=str(thread.id),
                assistant_id=str(thread.assistant_id) if thread.assistant_id else "",
                created_at=message.created.timestamp(),
                object="thread.message",
                role=message.role.value,
                content=[],
                status=message.message_status.value
                if message.message_status != "pending"
                else "in_progress",
                run_id=str(message.run_id) if message.run_id else None,
                output_index=message.output_index,
            )
            attachments: list[Attachment] = []
            attachments_dict: dict[str, list[dict[str, str]]] = {}
            for attachment in message.file_search_attachments:
                attachments_dict.setdefault(attachment.file_id, []).append(
                    {"type": "file_search"}
                )

            for attachment in message.code_interpreter_attachments:
                attachments_dict.setdefault(attachment.file_id, []).append(
                    {"type": "code_interpreter"}
                )
            for file_id, tools in attachments_dict.items():
                attachments.append({"file_id": file_id, "tools": tools})

            _message.attachments = attachments
            for content in message.content:
                match content.type:
                    case schemas.MessagePartType.INPUT_TEXT:
                        _message.content.append(
                            schemas.ThreadTextContentBlock(
                                text=schemas.ThreadText(
                                    value=content.text, annotations=[]
                                ),
                                type="text",
                            )
                        )
                    case schemas.MessagePartType.INPUT_IMAGE:
                        _message.content.append(
                            ImageFileContentBlock(
                                type="image_file",
                                image_file=ImageFile(
                                    file_id=content.input_image_file_id,
                                ),
                            )
                        )
                    case schemas.MessagePartType.OUTPUT_TEXT:
                        _annotations: list[Annotation] = []
                        _file_ids_file_citation_annotation: set[str] = set()
                        if content.annotations:
                            for annotation in content.annotations:
                                if (
                                    annotation.type
                                    == schemas.AnnotationType.FILE_CITATION
                                    and show_file_search_document_names
                                ):
                                    _file_record = file_search_results.get(
                                        annotation.file_id
                                    )
                                    if _file_record:
                                        if (
                                            annotation.file_id
                                            not in _file_ids_file_citation_annotation
                                        ):
                                            _file_ids_file_citation_annotation.add(
                                                annotation.file_id
                                            )
                                            _file_citation = FileCitationAnnotation(
                                                end_index=annotation.end_index or 0,
                                                start_index=annotation.start_index or 0,
                                                file_citation=FileCitation(
                                                    file_id=_file_record.file_id,
                                                    file_name=_file_record.filename,
                                                    quote=_file_record.text
                                                    if show_file_search_result_quotes
                                                    else "",
                                                ),
                                                text="responses_v3",
                                                type="file_citation",
                                            )
                                            _annotations.append(_file_citation)
                                elif (
                                    annotation.type == schemas.AnnotationType.FILE_PATH
                                    or (
                                        annotation.type
                                        == schemas.AnnotationType.CONTAINER_FILE_CITATION
                                        and not annotation.vision_file_id
                                    )
                                ):
                                    _annotations.append(
                                        FilePathAnnotation(
                                            type="file_path",
                                            end_index=annotation.end_index,
                                            start_index=annotation.start_index,
                                            file_path=FilePath(
                                                file_id=str(
                                                    annotation.file_object_id
                                                    or annotation.file_id
                                                ),
                                            ),
                                            text=annotation.text or "",
                                        )
                                    )
                                elif (
                                    annotation.type
                                    == schemas.AnnotationType.CONTAINER_FILE_CITATION
                                    and annotation.vision_file_id
                                ):
                                    _message.content.insert(
                                        0,
                                        ImageFileContentBlock(
                                            image_file=ImageFile(
                                                file_id=annotation.vision_file_id,
                                            ),
                                            type="image_file",
                                        ),
                                    )
                                elif (
                                    annotation.type
                                    == schemas.AnnotationType.URL_CITATION
                                ):
                                    _annotations.append(
                                        AnnotationURLCitation(
                                            type="url_citation",
                                            end_index=annotation.end_index or 0,
                                            start_index=annotation.start_index or 0,
                                            url=annotation.url or "",
                                            title=annotation.title or "",
                                            text=annotation.text or "",
                                        )
                                    )

                        _message.content.append(
                            schemas.ThreadTextContentBlock(
                                type="text",
                                text=schemas.ThreadText(
                                    value=content.text,
                                    annotations=_annotations,
                                ),
                            )
                        )

            if not message.user_id:
                thread_messages.append(_message)
                continue

            if int(message.user_id) in current_user_ids:
                is_current_user = True
                _message.metadata = {"is_current_user": True}
            else:
                _message.metadata = {"is_current_user": False}

            if str(message.user_id) not in users:
                if is_current_user:
                    _message.metadata["name"] = "Me"
                else:
                    _message.metadata["name"] = "Unknown User"
            else:
                _message.metadata["name"] = (
                    name(users[str(message.user_id)])
                    if thread.display_user_info and is_supervisor
                    else "Anonymous User"
                    if thread.private
                    else pseudonym(thread, users[str(message.user_id)])
                )
            thread_messages.append(_message)

        return {
            "messages": thread_messages,
            "ci_messages": [],
            "fs_messages": file_search_calls,
            "ws_messages": web_search_calls,
            "mcp_messages": mcp_messages,
            "reasoning_messages": reasoning_messages,
            "limit": limit,
            "has_more": has_more_runs,
        }
    else:
        raise HTTPException(status_code=400, detail="Invalid thread version")


@v1.get(
    "/class/{class_id}/thread/{thread_id}/details",
    dependencies=[Depends(Authz("admin", "class:{class_id}"))],
)
async def get_thread_details(
    class_id: str,
    thread_id: str,
    request: StateRequest,
):
    thread = await models.Thread.get_by_id_extended_details(
        request.state["db"], int(thread_id)
    )

    if thread is None or thread.class_id != int(class_id):
        raise HTTPException(status_code=404, detail="Thread not found")

    coalesced = []
    for run in thread.runs:
        for msg in run.messages:
            msg._kind = "message"  # transient attribute, not persisted
            coalesced.append(msg)

        for tool_call in run.tool_calls:
            tool_call._kind = "tool_call"
            coalesced.append(tool_call)

        for step in run.reasoning_steps:
            step._kind = "reasoning_step"
            coalesced.append(step)
    coalesced.sort(key=lambda x: getattr(x, "output_index", 0))

    return {
        "conversation_items": coalesced,
        "thread": thread,
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
    request: StateRequest,
    openai_client: OpenAIClient,
    block: bool = True,
):
    TIMEOUT = 60  # seconds
    thread = await models.Thread.get_by_id(request.state["db"], int(thread_id))

    if thread.version <= 2:
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
    elif thread.version == 3:
        last_run = await models.Thread.get_latest_run_by_thread_id(
            request.state["db"], thread.id
        )

        if not last_run:
            return {"thread": thread, "run": None}

        if not block:
            return {"thread": thread, "run": last_run}

        t0 = time.monotonic()
        while last_run.status not in {
            schemas.RunStatus.COMPLETED,
            schemas.RunStatus.FAILED,
            schemas.RunStatus.INCOMPLETE,
        }:
            if time.monotonic() - t0 > TIMEOUT:
                raise HTTPException(
                    status_code=504, detail="Timeout waiting for run to complete"
                )
            # Poll until the run is complete.
            await asyncio.sleep(1)
            try:
                await request.state["db"].refresh(last_run)
            except Exception as e:
                logger.exception("Error refreshing run status: %s", e)
                # Continue polling

        return {"thread": thread, "run": last_run}
    else:
        raise HTTPException(status_code=400, detail="Invalid thread version")


@v1.get(
    "/threads/recent",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Threads,
)
async def list_recent_threads(
    request: StateRequest, limit: int = 5, before: str | None = None
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
    thread_ids = await request.state["authz"].list(
        f"user:{request.state['session'].user.id}",
        "can_participate",
        "thread",
    )
    threads = await models.Thread.get_n_by_id(
        request.state["db"],
        thread_ids,
        limit,
        before=current_latest_time,
    )
    if not threads:
        return {"threads": []}

    class_ids = set(t.class_id for t in threads if t.class_id is not None)

    is_supervisor_in_class_check = await request.state["authz"].check(
        [
            (
                f"user:{request.state['session'].user.id}",
                "supervisor",
                f"class:{class_id}",
            )
            for class_id in class_ids
        ]
    )
    is_supervisor_dict = {
        class_id: is_supervisor
        for class_id, is_supervisor in zip(class_ids, is_supervisor_in_class_check)
    }

    return {
        "threads": process_threads(
            threads, request.state["session"].user.id, is_supervisor_dict
        )
    }


@v1.get(
    "/threads",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Threads,
)
async def list_all_threads(
    request: StateRequest,
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
    expect_high_cardinality = await request.state["authz"].test(
        f"user:{request.state['session'].user.id}",
        "admin",
        request.state["authz"].root,
    )

    if expect_high_cardinality:
        logger.info("Using high-cardinality strategy for all_threads query")

        async def _batch_check_can_view(
            threads: list[models.Thread],
        ) -> list[models.Thread]:
            allows = await request.state["authz"].check(
                [
                    (
                        f"user:{request.state['session'].user.id}",
                        "can_view",
                        f"thread:{t.id}",
                    )
                    for t in threads
                ]
            )
            return [t for t, allow in zip(threads, allows) if allow]

        threads = await models.Thread.get_n(
            request.state["db"],
            n=limit,
            before=current_latest_time,
            class_id=class_id,
            private=private,
            filter_batch=_batch_check_can_view,
        )
    else:
        logger.info("Using low-cardinality strategy for all_threads query")
        thread_ids = await request.state["authz"].list(
            f"user:{request.state['session'].user.id}",
            "can_view",
            "thread",
        )
        logger.info("/threads: FGA Returned %s thread_ids", len(thread_ids))
        threads = await models.Thread.get_n_by_id(
            request.state["db"],
            thread_ids,
            limit,
            before=current_latest_time,
            private=private,
            class_id=class_id,
        )

    if not threads:
        return {"threads": []}

    class_ids = set(t.class_id for t in threads if t.class_id is not None)

    is_supervisor_in_class_check = await request.state["authz"].check(
        [
            (
                f"user:{request.state['session'].user.id}",
                "supervisor",
                f"class:{class_id}",
            )
            for class_id in class_ids
        ]
    )
    is_supervisor_dict = {
        class_id: is_supervisor
        for class_id, is_supervisor in zip(class_ids, is_supervisor_in_class_check)
    }

    return {
        "threads": process_threads(
            threads, request.state["session"].user.id, is_supervisor_dict
        )
    }


@v1.get(
    "/class/{class_id}/threads",
    dependencies=[Depends(Authz("can_view", "class:{class_id}"))],
    response_model=schemas.Threads,
)
async def list_threads(
    class_id: str, request: StateRequest, limit: int = 20, before: str | None = None
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
    can_view_coro = request.state["authz"].list(
        f"user:{request.state['session'].user.id}",
        "can_view",
        "thread",
    )
    in_class_coro = request.state["authz"].list(
        f"class:{class_id}",
        "parent",
        "thread",
    )
    can_view, in_class = await asyncio.gather(can_view_coro, in_class_coro)
    thread_ids = list(set(can_view) & set(in_class))
    threads = await models.Thread.get_n_by_id(
        request.state["db"],
        thread_ids,
        limit,
        before=current_latest_time,
    )

    if not threads:
        return {"threads": []}

    class_ids = set(t.class_id for t in threads if t.class_id is not None)

    is_supervisor_in_class_check = await request.state["authz"].check(
        [
            (
                f"user:{request.state['session'].user.id}",
                "supervisor",
                f"class:{class_id}",
            )
            for class_id in class_ids
        ]
    )
    is_supervisor_dict = {
        class_id: is_supervisor
        for class_id, is_supervisor in zip(class_ids, is_supervisor_in_class_check)
    }

    return {
        "threads": process_threads(
            threads, request.state["session"].user.id, is_supervisor_dict
        )
    }


@v1.post(
    "/class/{class_id}/thread/audio",
    dependencies=[Depends(Authz("can_create_thread", "class:{class_id}"))],
    response_model=schemas.ThreadWithOptionalToken,
)
async def create_audio_thread(
    class_id: str,
    req: schemas.CreateAudioThread,
    request: StateRequest,
    openai_client: OpenAIClient,
):
    parties = list[models.User]()
    thread = None

    anonymous_session: models.AnonymousSession | None = None
    anonymous_user: models.User | None = None
    if request.state["is_anonymous"]:
        anonymous_session = await models.AnonymousSession.create(
            request.state["db"],
            str(uuid.uuid7()),
            user_id=request.state["anonymous_session"].user.id,
        )
        anonymous_user = anonymous_session.user

    anonymous_session_with_logged_in_user = False
    parties_ids = req.parties or []
    if (
        request.state["session"].user is not None
        and request.state["session"].status != schemas.SessionStatus.ANONYMOUS
    ):
        anonymous_session_with_logged_in_user = True
        if request.state["session"].user.id not in parties_ids:
            parties_ids.append(request.state["session"].user.id)

    assistant = await models.Assistant.get_by_id(request.state["db"], req.assistant_id)
    if not assistant:
        raise HTTPException(
            status_code=404,
            detail="Could not find the assistant you specified. Please try again.",
        )

    class_ = None
    if assistant.version <= 2:
        try:
            thread, class_, parties = await asyncio.gather(
                openai_client.beta.threads.create(
                    metadata={
                        "user_id": str(request.state["session"].user.id),
                    },
                ),
                models.Class.get_by_id(request.state["db"], int(class_id)),
                models.User.get_all_by_id(request.state["db"], parties_ids),
            )
        except openai.InternalServerError:
            logger.exception("Error creating thread")
            if thread:
                await openai_client.beta.threads.delete(thread.id)
            raise HTTPException(
                status_code=503,
                detail="OpenAI is experiencing issues so we can't create your conversation right now. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )
        except (openai.APIError, Exception):
            logger.exception("Error creating thread")
            if thread:
                await openai_client.beta.threads.delete(thread.id)
            raise HTTPException(
                status_code=400,
                detail="Something went wrong while creating your conversation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )
        if not thread:
            raise HTTPException(
                status_code=500,
                detail="We faced an error while creating your conversation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )
    elif assistant.version == 3:
        try:
            class_, parties = await asyncio.gather(
                models.Class.get_by_id(request.state["db"], int(class_id)),
                models.User.get_all_by_id(request.state["db"], parties_ids),
            )
        except (openai.APIError, Exception):
            logger.exception("Error creating thread")
            raise HTTPException(
                status_code=400,
                detail="Something went wrong while creating your conversation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid assistant version",
        )

    if not class_:
        if thread:
            await openai_client.beta.threads.delete(thread.id)
        raise HTTPException(
            status_code=404,
            detail="Class not found",
        )

    all_parties = parties or []
    if anonymous_user:
        all_parties.append(anonymous_user)
    new_thread = {
        "name": "Audio Conversation",
        "class_id": int(class_id),
        "private": True if all_parties else False,
        "interaction_mode": "voice",
        "users": all_parties,
        "thread_id": thread.id if thread else None,
        "anonymous_sessions": [anonymous_session] if anonymous_session else [],
        "conversation_id": req.conversation_id,
        "assistant_id": req.assistant_id,
        "vector_store_id": None,
        "code_interpreter_file_ids": [],
        "image_file_ids": [],
        "tools_available": json.dumps([]),
        "version": assistant.version,
        "last_activity": func.now(),
        "instructions": format_instructions(
            assistant.instructions,
            assistant.use_latex,
            assistant.use_image_descriptions,
            thread_id=thread.id if thread else None,
            user_id=request.state["session"].user.id,
        ),
        "timezone": req.timezone,
        "display_user_info": assistant.should_record_user_information
        and not class_.private,
    }

    result: None | models.Thread = None
    try:
        result = await models.Thread.create(request.state["db"], new_thread)
        if assistant.version == 3:
            result.instructions = format_instructions(
                assistant.instructions,
                assistant.use_latex,
                assistant.use_image_descriptions,
                thread_id=result.id,
                user_id=request.state["session"].user.id,
            )
            request.state["db"].add(result)
            await request.state["db"].flush()
            await request.state["db"].refresh(result)

        grants = [
            (f"class:{class_id}", "parent", f"thread:{result.id}"),
        ] + [(f"user:{p.id}", "party", f"thread:{result.id}") for p in parties]
        if anonymous_session:
            grants.extend(
                [
                    (
                        f"anonymous_user:{anonymous_session.session_token}",
                        "anonymous_party",
                        f"thread:{result.id}",
                    ),
                    (
                        f"anonymous_user:{anonymous_session.session_token}",
                        "can_upload_user_files",
                        f"class:{class_id}",
                    ),
                ]
            )
            if anonymous_session_with_logged_in_user:
                grants.append(
                    (
                        f"user:{request.state['session'].user.id}",
                        "anonymous_party",
                        f"thread:{result.id}",
                    )
                )
        await request.state["authz"].write(grant=grants)

        return {
            "thread": result,
            "session_token": anonymous_session.session_token
            if anonymous_session
            else None,
        }
    except Exception as e:
        logger.exception("Error creating thread: %s", e)
        if thread:
            # If the thread was created, delete it
            await openai_client.beta.threads.delete(thread.id)
        if result:
            # Delete users-threads mapping
            for user in result.users:
                result.users.remove(user)
            await result.delete(request.state["db"])
        raise e


@v1.post(
    "/class/{class_id}/thread/lecture",
    dependencies=[Depends(Authz("can_create_thread", "class:{class_id}"))],
    response_model=schemas.ThreadWithOptionalToken,
)
async def create_lecture_thread(
    class_id: str,
    req: schemas.CreateLectureThread,
    request: StateRequest,
):
    if request.state["is_anonymous"]:
        raise HTTPException(
            status_code=403,
            detail="Can't create a Lecture presentation with an anonymous session. Please sign in!",
        )

    parties_ids = req.parties or []
    if (
        request.state["session"].user is not None
        and request.state["session"].status != schemas.SessionStatus.ANONYMOUS
    ):
        if request.state["session"].user.id not in parties_ids:
            parties_ids.append(request.state["session"].user.id)

    assistant = await models.Assistant.get_by_id_with_lecture_video(
        request.state["db"], int(req.assistant_id)
    )
    if not assistant:
        raise HTTPException(
            status_code=404,
            detail="Could not find the assistant you specified. Please try again.",
        )

    if assistant.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO:
        raise HTTPException(
            status_code=400,
            detail="This assistant is not compatible with this thread creation endpoint. Provide a lecture_video assistant.",
        )

    if not assistant.lecture_video:
        raise HTTPException(
            status_code=400,
            detail="This assistant does not have a lecture video attached. Unable to create Lecture Presentation",
        )

    lecture_video_id = assistant.lecture_video_id

    if assistant.version != 3:
        raise HTTPException(
            status_code=400,
            detail="Lecture presentation can only be created using v3 assistants.",
        )

    class_, parties = await asyncio.gather(
        models.Class.get_by_id(request.state["db"], int(class_id)),
        models.User.get_all_by_id(request.state["db"], parties_ids),
    )

    if not class_:
        raise HTTPException(
            status_code=404,
            detail="Class not found",
        )
    all_parties = parties or []
    new_thread = {
        "name": "Lecture Presentation",
        "class_id": int(class_id),
        "private": True if all_parties else False,
        "interaction_mode": "lecture_video",
        "users": all_parties,
        "thread_id": None,
        "anonymous_sessions": [],
        "conversation_id": None,
        "assistant_id": req.assistant_id,
        "vector_store_id": None,
        "code_interpreter_file_ids": [],
        "image_file_ids": [],
        "tools_available": json.dumps([]),
        "version": assistant.version,
        "last_activity": func.now(),
        "instructions": None,
        "timezone": req.timezone,
        "lecture_video_id": lecture_video_id,
        "display_user_info": assistant.should_record_user_information
        and not class_.private,
    }

    result: None | models.Thread = None
    try:
        result = await models.Thread.create(request.state["db"], new_thread)
        result.instructions = format_instructions(
            assistant.instructions,
            assistant.use_latex,
            assistant.use_image_descriptions,
            thread_id=result.id,
            user_id=request.state["session"].user.id,
        )
        request.state["db"].add(result)
        await request.state["db"].flush()
        await request.state["db"].refresh(result)

        grants = [
            (f"class:{class_id}", "parent", f"thread:{result.id}"),
        ] + [(f"user:{p.id}", "party", f"thread:{result.id}") for p in parties]
        await request.state["authz"].write(grant=grants)

        return {
            "thread": result,
        }
    except Exception as e:
        logger.exception("Error creating thread: %s", e)
        if result:
            # Delete users-threads mapping
            for user in result.users:
                result.users.remove(user)
            await result.delete(request.state["db"])
        raise HTTPException(
            status_code=400,
            detail="Something went wrong while creating your Lecture presentation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
        ) from e


@v1.post(
    "/class/{class_id}/thread",
    dependencies=[Depends(Authz("can_create_thread", "class:{class_id}"))],
    response_model=schemas.ThreadWithOptionalToken,
)
async def create_thread(
    class_id: str,
    req: schemas.CreateThread,
    request: StateRequest,
    openai_client: OpenAIClient,
):
    parties = list[models.User]()
    vector_store_id = None
    vector_store_object_id = None
    tool_resources: ToolResources = {}

    assistant = await models.Assistant.get_by_id(request.state["db"], req.assistant_id)

    if not assistant:
        raise HTTPException(
            status_code=404,
            detail="Could not find the assistant you specified. Please try again.",
        )

    if assistant.interaction_mode in (
        schemas.InteractionMode.LECTURE_VIDEO,
        schemas.InteractionMode.VOICE,
    ):
        raise HTTPException(
            status_code=400,
            detail="This assistant requires a dedicated thread creation endpoint.",
        )

    if assistant.assistant_should_message_first and req.message:
        raise HTTPException(
            status_code=400,
            detail="The assistant you selected is configured to message first. Please do not include a message in your request.",
        )

    if not assistant.assistant_should_message_first and not req.message:
        raise HTTPException(
            status_code=400,
            detail="Please include a message in your request.",
        )

    if not req.message and (
        req.vision_file_ids or req.file_search_file_ids or req.code_interpreter_file_ids
    ):
        raise HTTPException(
            status_code=400,
            detail="You must provide a message if you are uploading files or images.",
        )

    # Check if user file uploads are allowed for this assistant
    if not assistant.allow_user_file_uploads and (
        req.file_search_file_ids or req.code_interpreter_file_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="You can't upload files with this assistant. Remove the files and try again.",
        )

    if not assistant.allow_user_image_uploads and req.vision_file_ids:
        raise HTTPException(
            status_code=403,
            detail="You can't upload photos with this assistant. Remove the photos and try again.",
        )

    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    if not class_:
        raise HTTPException(
            status_code=404,
            detail="Class not found",
        )

    if req.file_search_file_ids:
        vector_store_id, vector_store_object_id = await create_vector_store(
            request.state["db"],
            openai_client,
            class_id,
            req.file_search_file_ids,
            type=schemas.VectorStoreType.THREAD,
            upload_to_oai=assistant.version == 3,
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
            "text": (req.message or "") + (vision_image_descriptions or ""),
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

    anonymous_session: models.AnonymousSession | None = None
    anonymous_user: models.User | None = None
    if request.state["is_anonymous"]:
        anonymous_session = await models.AnonymousSession.create(
            request.state["db"],
            str(uuid.uuid7()),
            user_id=request.state["anonymous_session"].user.id,
        )
        anonymous_user = anonymous_session.user

    anonymous_session_with_logged_in_user = False
    parties_ids = req.parties or []
    if (
        request.state["session"].user is not None
        and request.state["session"].status != schemas.SessionStatus.ANONYMOUS
    ):
        anonymous_session_with_logged_in_user = True
        if request.state["session"].user.id not in parties_ids:
            parties_ids.append(request.state["session"].user.id)

    metadata: dict[str, str | int] = {
        "user_id": str(request.state["session"].user.id),
    }

    if request.state["anonymous_share_token"] is not None:
        metadata["share_token"] = str(request.state["anonymous_share_token"])
    if anonymous_session is not None:
        metadata["anonymous_session_token"] = str(anonymous_session.session_token)

    tools_export = req.model_dump(include={"tools_available"})

    if assistant.version <= 2:
        try:
            thread, parties, thread_name = await asyncio.gather(
                openai_client.beta.threads.create(
                    messages=[
                        {
                            "metadata": metadata,
                            "role": "user",
                            "content": messageContent,
                            "attachments": attachments,
                        }
                    ]
                    if req.message
                    else [],
                    tool_resources=tool_resources,
                ),
                models.User.get_all_by_id(request.state["db"], parties_ids),
                get_initial_thread_conversation_name(
                    openai_client,
                    request.state["db"],
                    req.message,
                    req.vision_file_ids,
                    class_id,
                ),
            )
        except openai.InternalServerError:
            logger.exception("Error creating thread")
            if vector_store_id:
                await openai_client.vector_stores.delete(vector_store_id)
            if thread:
                await openai_client.beta.threads.delete(thread.id)
            raise HTTPException(
                status_code=503,
                detail="OpenAI is experiencing issues so we can't create your conversation right now. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )
        except (openai.APIError, Exception):
            logger.exception("Error creating thread")
            if vector_store_id:
                await openai_client.vector_stores.delete(vector_store_id)
            if thread:
                await openai_client.beta.threads.delete(thread.id)
            raise HTTPException(
                status_code=400,
                detail="Something went wrong while creating your conversation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )

        if not thread:
            if vector_store_id:
                await openai_client.vector_stores.delete(vector_store_id)
            raise HTTPException(
                status_code=500,
                detail="We faced an error while creating your conversation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )
    elif assistant.version == 3:
        try:
            parties, thread_name = await asyncio.gather(
                models.User.get_all_by_id(request.state["db"], parties_ids),
                get_initial_thread_conversation_name(
                    openai_client,
                    request.state["db"],
                    req.message,
                    req.vision_file_ids,
                    class_id,
                ),
            )
        except openai.InternalServerError:
            logger.exception("Error creating thread")
            if vector_store_id:
                await openai_client.vector_stores.delete(vector_store_id)
            raise HTTPException(
                status_code=503,
                detail="OpenAI is experiencing issues so we can't create your conversation right now. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )
        except (openai.APIError, Exception):
            logger.exception("Error creating thread")
            if vector_store_id:
                await openai_client.vector_stores.delete(vector_store_id)
            raise HTTPException(
                status_code=400,
                detail="Something went wrong while creating your conversation. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
            )
    else:
        if vector_store_id:
            await openai_client.vector_stores.delete(vector_store_id)
        raise HTTPException(
            status_code=400,
            detail="Unsupported assistant version.",
        )
    all_parties = parties or []
    if anonymous_user:
        all_parties.append(anonymous_user)
    new_thread = {
        "name": thread_name,
        "class_id": int(class_id),
        "private": True if all_parties else False,
        "users": all_parties,
        "thread_id": thread.id if thread else None,
        "anonymous_sessions": [anonymous_session] if anonymous_session else [],
        "conversation_id": req.conversation_id,
        "assistant_id": req.assistant_id,
        "vector_store_id": vector_store_object_id,
        "code_interpreter_file_ids": req.code_interpreter_file_ids or [],
        "image_file_ids": req.vision_file_ids or [],
        "tools_available": json.dumps(tools_export["tools_available"] or []),
        "version": assistant.version,
        "last_activity": func.now(),
        "instructions": format_instructions(
            assistant.instructions,
            assistant.use_latex,
            assistant.use_image_descriptions,
            thread_id=thread.id if thread and thread.id else None,
            user_id=request.state["session"].user.id,
        )
        if thread and thread.id
        else None,
        "timezone": req.timezone,
        "display_user_info": assistant.should_record_user_information
        and not class_.private,
    }

    thread_db_record: None | models.Thread = None
    try:
        thread_db_record = await models.Thread.create(request.state["db"], new_thread)

        mcp_tool_ids = await models.Assistant.get_mcp_tool_ids_by_assistant_id(
            request.state["db"], assistant.id
        )
        if mcp_tool_ids:
            await models.Thread.add_mcp_server_tools(
                request.state["db"], thread_db_record.id, mcp_tool_ids
            )

        if assistant.version == 3:
            thread_db_record.instructions = format_instructions(
                assistant.instructions,
                assistant.use_latex,
                assistant.use_image_descriptions,
                thread_id=thread_db_record.id,
                user_id=request.state["session"].user.id,
            )
            tasks_to_run = []

            async def empty_file_list() -> list[models.File]:
                return []

            if req.code_interpreter_file_ids:
                tasks_to_run.append(
                    models.File.get_all_by_file_id(
                        request.state["db"], req.code_interpreter_file_ids
                    )
                )
            else:
                tasks_to_run.append(empty_file_list())  # placeholder

            if req.file_search_file_ids:
                tasks_to_run.append(
                    models.File.get_all_by_file_id(
                        request.state["db"], req.file_search_file_ids
                    )
                )
            else:
                tasks_to_run.append(empty_file_list())  # placeholder

            code_interpreter_files, file_search_files = await asyncio.gather(
                *tasks_to_run
            )

            messageContentParts: list[models.MessagePart] = []
            part_index = 0
            for part in messageContent:
                if part["type"] == "text":
                    messageContentParts.append(
                        models.MessagePart(
                            part_index=part_index,
                            type=schemas.MessagePartType.INPUT_TEXT,
                            text=part["text"],
                        )
                    )
                elif part["type"] == "image_file":
                    messageContentParts.append(
                        models.MessagePart(
                            part_index=part_index,
                            type=schemas.MessagePartType.INPUT_IMAGE,
                            input_image_file_id=part["image_file"]["file_id"],
                        )
                    )
                part_index += 1

            run = models.Run(
                status=schemas.RunStatus.PENDING,
                thread_id=thread_db_record.id,
                creator_id=request.state["session"].user.id,
                assistant_id=assistant.id,
                model=assistant.model,
                verbosity=assistant.verbosity,
                reasoning_effort=assistant.reasoning_effort,
                temperature=assistant.temperature,
                tools_available=thread_db_record.tools_available,
                instructions=inject_timestamp_to_instructions(
                    thread_db_record.instructions, thread_db_record.timezone
                ),
                messages=[
                    models.Message(
                        thread_id=thread_db_record.id,
                        output_index=0,
                        message_status=schemas.MessageStatus.COMPLETED,
                        role=schemas.MessageRole.USER,
                        user_id=request.state["session"].user.id,
                        content=messageContentParts,
                        file_search_attachments=file_search_files,
                        code_interpreter_attachments=code_interpreter_files,
                    )
                ]
                if messageContentParts
                else [],
            )

            request.state["db"].add(run)
            await request.state["db"].flush()

            if mcp_tool_ids:
                await models.Run.add_mcp_server_tools(
                    request.state["db"], run.id, mcp_tool_ids
                )

        grants = [
            (f"class:{class_id}", "parent", f"thread:{thread_db_record.id}"),
        ] + [
            (f"user:{p.id}", "party", f"thread:{thread_db_record.id}") for p in parties
        ]
        revokes = []
        if anonymous_session:
            grants.extend(
                [
                    (
                        f"anonymous_user:{anonymous_session.session_token}",
                        "anonymous_party",
                        f"thread:{thread_db_record.id}",
                    ),
                    (
                        f"anonymous_user:{anonymous_session.session_token}",
                        "can_upload_user_files",
                        f"class:{class_id}",
                    ),
                ]
            )
            if anonymous_session_with_logged_in_user:
                grants.append(
                    (
                        f"user:{request.state['session'].user.id}",
                        "anonymous_party",
                        f"thread:{thread_db_record.id}",
                    )
                )
            if (
                req.file_search_file_ids
                or req.code_interpreter_file_ids
                or req.vision_file_ids
            ):
                all_file_ids = (
                    (req.file_search_file_ids or [])
                    + (req.code_interpreter_file_ids or [])
                    + (req.vision_file_ids or [])
                )
                files = await models.File.get_all_by_file_id(
                    request.state["db"], all_file_ids
                )
                for file in files:
                    grants.append(
                        (
                            f"anonymous_user:{anonymous_session.session_token}",
                            "owner",
                            f"user_file:{file.id}",
                        )
                    )
                    # Revoke can_delete permission from the anonymous link
                    # now that the file is associated with an anonymous session
                    if (
                        request.state["anonymous_share_token"]
                        and file.anonymous_link_id == request.state["anonymous_link_id"]
                    ):
                        revokes.append(
                            (
                                f"anonymous_link:{request.state['anonymous_share_token']}",
                                "can_delete",
                                f"user_file:{file.id}",
                            )
                        )

                    file.anonymous_session_id = anonymous_session.id
                    request.state["db"].add(file)
                if files:
                    await request.state["db"].flush()

        await request.state["authz"].write_safe(grant=grants, revoke=revokes)

        return {
            "thread": thread_db_record,
            "session_token": anonymous_session.session_token
            if anonymous_session
            else None,
        }
    except Exception as e:
        logger.exception("Error creating thread: %s", e)
        if vector_store_id:
            await openai_client.vector_stores.delete(vector_store_id)
        if thread:
            await openai_client.beta.threads.delete(thread.id)
        if thread_db_record:
            await thread_db_record.delete(request.state["db"])
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
    request: StateRequest,
    openai_client: OpenAIClient,
    req: schemas.CreateThreadRunRequest = Body(default=None),
):
    thread = await models.Thread.get_by_id_with_ci_file_ids(
        request.state["db"], int(thread_id)
    )
    asst = await models.Assistant.get_by_id(request.state["db"], thread.assistant_id)
    mcp_tool_ids = await models.Thread.get_mcp_tool_ids_by_thread_id(
        request.state["db"], thread.id
    )

    if not thread or not asst:
        raise HTTPException(
            status_code=404,
            detail="We could not find the thread or assistant you specified. Please try again.",
        )

    if thread.version == 3:
        try:
            last_run = await models.Thread.get_latest_run_by_thread_id(
                request.state["db"], thread.id
            )
            file_search_file_ids: list[str] = []

            if last_run and last_run.status == schemas.RunStatus.PENDING:
                run_to_complete = last_run
                file_search_file_ids = (
                    await models.Run.get_file_search_files_from_messages(
                        request.state["db"], last_run.id
                    )
                )
            elif last_run is None or (
                last_run
                and last_run.status
                in {
                    schemas.RunStatus.COMPLETED,
                    schemas.RunStatus.FAILED,
                    schemas.RunStatus.INCOMPLETE,
                }
            ):
                if not thread.instructions:
                    thread.instructions = format_instructions(
                        asst.instructions,
                        asst.use_latex,
                        asst.use_image_descriptions,
                        thread_id=str(thread.id),
                        user_id=request.state["session"].user.id,
                    )
                    request.state["db"].add(thread)
                    await request.state["db"].flush()
                    await request.state["db"].refresh(thread)

                run_to_complete = models.Run(
                    status=schemas.RunStatus.PENDING,
                    thread_id=thread.id,
                    creator_id=request.state["session"].user.id,
                    assistant_id=asst.id,
                    model=asst.model,
                    reasoning_effort=asst.reasoning_effort,
                    temperature=asst.temperature,
                    tools_available=thread.tools_available,
                    instructions=inject_timestamp_to_instructions(
                        thread.instructions, req.timezone if req else thread.timezone
                    ),
                    verbosity=asst.verbosity,
                )
                request.state["db"].add(run_to_complete)
                await request.state["db"].flush()
                await request.state["db"].refresh(run_to_complete)
                file_search_file_ids = []
            else:
                raise HTTPException(
                    status_code=409,
                    detail="OpenAI is still processing your last request. We're fetching the latest status...",
                )

            async def get_vector_store_id_by_id_or_none(
                db: AsyncSession, vector_store_id: int | None
            ) -> str | None:
                if vector_store_id:
                    return await models.VectorStore.get_vector_store_id_by_id(
                        db, vector_store_id
                    )
                return None

            [
                file_names,
                thread_vector_store_id,
                assistant_vector_store_id,
                is_supervisor_check,
            ] = await asyncio.gather(
                models.Thread.get_file_search_files(request.state["db"], thread.id),
                get_vector_store_id_by_id_or_none(
                    request.state["db"], thread.vector_store_id
                ),
                get_vector_store_id_by_id_or_none(
                    request.state["db"], asst.vector_store_id
                ),
                request.state["authz"].check(
                    [
                        (
                            f"user:{request.state['session'].user.id}",
                            "supervisor",
                            f"class:{class_id}",
                        )
                    ]
                ),
            )

            is_supervisor = is_supervisor_check[0]
            mcp_server_tools_by_server_label: dict[str, models.MCPServerTool] = {}

            if mcp_tool_ids:
                mcp_server_tools = await models.Run.add_mcp_server_tools_return_tools(
                    request.state["db"], run_to_complete.id, mcp_tool_ids
                )
                for tool in mcp_server_tools:
                    if tool.enabled:
                        mcp_server_tools_by_server_label[tool.server_label] = tool

            run_to_complete.status = schemas.RunStatus.QUEUED
            request.state["db"].add(run_to_complete)
            await request.state["db"].flush()
            await request.state["db"].refresh(run_to_complete)

            stream = run_response(
                openai_client,
                run=run_to_complete,
                class_id=class_id,
                file_names=file_names,
                assistant_vector_store_id=assistant_vector_store_id,
                thread_vector_store_id=thread_vector_store_id,
                attached_file_search_file_ids=file_search_file_ids,
                code_interpreter_file_ids=[
                    file.file_id for file in thread.code_interpreter_files
                ],
                mcp_server_tools_by_server_label=mcp_server_tools_by_server_label,
                user_auth=request.state["auth_user"],
                anonymous_user_auth=request.state["anonymous_session_token_auth"],
                anonymous_link_auth=request.state["anonymous_share_token_auth"],
                anonymous_session_id=request.state["anonymous_session_id"],
                anonymous_link_id=request.state["anonymous_link_id"],
                show_file_search_document_names=is_supervisor
                or not asst.hide_file_search_document_names,
                show_file_search_queries=is_supervisor
                or not asst.hide_file_search_queries,
                show_file_search_result_quotes=is_supervisor
                or not asst.hide_file_search_result_quotes,
                show_reasoning_summaries=is_supervisor
                or not asst.hide_reasoning_summaries,
                show_web_search_sources=is_supervisor
                or not asst.hide_web_search_sources,
                show_web_search_actions=is_supervisor
                or not asst.hide_web_search_actions,
                show_mcp_server_call_details=is_supervisor
                or not asst.hide_mcp_server_call_details,
            )
        except Exception as e:
            logger.exception("Error running thread")
            raise HTTPException(
                status_code=500,
                detail="We faced an error while sending your message. " + str(e),
            )
    elif thread.version <= 2:
        try:
            file_names = await models.Thread.get_file_search_files(
                request.state["db"], thread.id
            )
            vector_store_id = (
                await models.VectorStore.get_vector_store_id_by_id(
                    request.state["db"], thread.vector_store_id
                )
                if thread.vector_store_id
                else None
            )

            # One-time migration for threads that don't have instructions set
            if not thread.instructions:
                logger.info(
                    "Thread %s does not have instructions set, migrating from assistant instructions",
                    thread.id,
                )
                thread.instructions = format_instructions(
                    asst.instructions,
                    asst.use_latex,
                    asst.use_image_descriptions,
                    thread_id=thread.thread_id,
                    user_id=request.state["session"].user.id,
                )
                request.state["db"].add(thread)
                await request.state["db"].flush()
                await request.state["db"].refresh(thread)

            stream = run_thread(
                openai_client,
                class_id=class_id,
                thread_id=thread.thread_id,
                assistant_id=asst.assistant_id,
                message=[],
                file_names=file_names,
                vector_store_id=vector_store_id,
                instructions=inject_timestamp_to_instructions(
                    thread.instructions, req.timezone if req else thread.timezone
                ),
            )
        except Exception as e:
            logger.exception("Error running thread")
            raise HTTPException(
                status_code=500,
                detail="We faced an error while sending your message. " + str(e),
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid thread version",
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
    request: StateRequest,
    openai_client: OpenAIClient,
):
    mcp_tool_ids: list[int] = []
    try:
        thread = await models.Thread.get_by_id(request.state["db"], int(thread_id))
        if thread.tools_available and "mcp_server" in thread.tools_available:
            mcp_tool_ids = await models.Thread.get_mcp_tool_ids_by_thread_id(
                request.state["db"], thread.id
            )

        tool_resources: ToolResources = {}

        # Check that assistant exists
        if not thread.assistant_id:
            raise HTTPException(
                status_code=404,
                detail="The assistant for this thread no longer exists.",
            )

        # Check user has permission to view this assistant
        if not (
            await request.state["authz"].check(
                [
                    (
                        request.state["auth_user"]
                        if not request.state["is_anonymous"]
                        else request.state["anonymous_share_token_auth"],
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

        if thread.version <= 2:
            last_runs_result = await openai_client.beta.threads.runs.list(
                thread.thread_id, limit=1, order="desc"
            )
            last_run = last_runs_result.data[0] if last_runs_result.data else None

            if not last_run:
                raise HTTPException(
                    status_code=500,
                    detail="OpenAI was unable to process your request. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
                )

            if last_run.status not in {
                "completed",
                "failed",
                "incomplete",
                "expired",
                "cancelled",
            }:
                raise HTTPException(
                    status_code=409,
                    detail="OpenAI is still processing your last request. We're fetching the latest status...",
                )
        elif thread.version == 3:
            last_run = await models.Thread.get_latest_run_by_thread_id(
                request.state["db"], thread.id
            )

            if not last_run:
                raise HTTPException(
                    status_code=500,
                    detail="We're having trouble fetching information about this conversation. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
                )

            if last_run.status in {
                schemas.RunStatus.QUEUED,
                schemas.RunStatus.PENDING,
                schemas.RunStatus.IN_PROGRESS,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="OpenAI is still processing your last request. We're fetching the latest status...",
                )
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid thread version",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error sending message to thread: %s", e)
        raise HTTPException(
            status_code=500,
            detail="We faced an error while sending your message. Please try again later. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
        )

    try:
        asst = await models.Assistant.get_by_id(
            request.state["db"], thread.assistant_id
        )

        # Check if user file uploads are allowed for this assistant
        if not asst.allow_user_file_uploads and (
            data.file_search_file_ids or data.code_interpreter_file_ids
        ):
            raise HTTPException(
                status_code=403,
                detail="You can't upload files with this assistant. Remove the files and try again.",
            )

        if not asst.allow_user_image_uploads and data.vision_file_ids:
            raise HTTPException(
                status_code=403,
                detail="You can't upload photos with this assistant. Remove the photos and try again.",
            )

        # When we reach 3 user messages, or if we failed to generate a title before, generate a new one. Only use the first 100 words of each user and assistant message to maintain a low token count.
        if thread.user_message_ct == 3 or thread.name is None:
            thread.name = await get_thread_conversation_name(
                openai_client,
                request.state["db"],
                data,
                str(thread.id) if thread.version == 3 else thread.thread_id,
                class_id,
                thread_version=thread.version,
            )

        if data.file_search_file_ids:
            if thread.vector_store_id:
                # Vector store already exists, update
                if thread.version == 3:
                    await append_vector_store_files(
                        request.state["db"],
                        openai_client,
                        thread.vector_store_id,
                        data.file_search_file_ids,
                    )
                else:
                    await add_vector_store_files_to_db(
                        request.state["db"],
                        thread.vector_store_id,
                        data.file_search_file_ids,
                    )
            else:
                # Store doesn't exist, create a new one
                # (empty, since we're adding files as attachments)
                # and relate files with new vector store
                vector_store_id, vector_store_object_id = await create_vector_store(
                    request.state["db"],
                    openai_client,
                    class_id,
                    data.file_search_file_ids,
                    type=schemas.VectorStoreType.THREAD,
                    upload_to_oai=thread.version == 3,
                )
                thread.vector_store_id = vector_store_object_id
                tool_resources["file_search"] = {"vector_store_ids": [vector_store_id]}

                existing_file_ids = [
                    file_id
                    async for file_id in models.Thread.get_file_ids_by_id(
                        request.state["db"], thread.id
                    )
                ]
                tool_resources["code_interpreter"] = {"file_ids": existing_file_ids}

                if thread.version <= 2:
                    try:
                        await openai_client.beta.threads.update(
                            thread.thread_id, tool_resources=tool_resources
                        )
                    except openai.BadRequestError as e:
                        raise HTTPException(
                            400,
                            get_details_from_api_error(
                                e, "OpenAI rejected this request"
                            ),
                        )

                thread.updated = func.now()

        if data.code_interpreter_file_ids:
            await models.Thread.add_code_interpreter_files(
                request.state["db"], thread.id, data.code_interpreter_file_ids
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
                request.state["db"], thread.id, data.vision_file_ids
            )
            [
                messageContent.append(
                    {"type": "image_file", "image_file": {"file_id": id}}
                )
                for id in data.vision_file_ids
            ]

        thread.last_activity = func.now()
        thread.user_message_ct += 1

        # One-time migration for threads that don't have instructions set
        if not thread.instructions:
            logger.info(
                "Thread %s does not have instructions set, migrating from assistant instructions",
                thread.id,
            )
            thread.instructions = format_instructions(
                asst.instructions,
                asst.use_latex,
                asst.use_image_descriptions,
                thread_id=thread.thread_id,
                user_id=request.state["session"].user.id,
            )
            request.state["db"].add(thread)
            await request.state["db"].flush()
            await request.state["db"].refresh(thread)
        else:
            request.state["db"].add(thread)

        metrics.inbound_messages.inc(
            app=config.public_url,
            class_=int(class_id),
            user=request.state["session"].user.id,
            thread=thread.thread_id,
        )

        file_names = await models.Thread.get_file_search_files(
            request.state["db"], thread.id
        )
        thread_vector_store_id = (
            await models.VectorStore.get_vector_store_id_by_id(
                request.state["db"], thread.vector_store_id
            )
            if thread.vector_store_id
            else None
        )

        if thread.version <= 2:
            metadata: dict[str, str | int] = {
                "user_id": str(request.state["session"].user.id),
            }
            if request.state["anonymous_share_token"] is not None:
                metadata["share_token"] = str(request.state["anonymous_share_token"])
            if request.state["anonymous_session_token"] is not None:
                metadata["anonymous_session_token"] = str(
                    request.state["anonymous_session_token"]
                )
            # Create a generator that will stream chunks to the client.
            stream = run_thread(
                openai_client,
                class_id=class_id,
                thread_id=thread.thread_id,
                assistant_id=asst.assistant_id,
                message=messageContent,
                metadata=metadata,
                file_names=file_names,
                file_search_file_ids=data.file_search_file_ids,
                code_interpreter_file_ids=data.code_interpreter_file_ids,
                vector_store_id=thread_vector_store_id,
                instructions=inject_timestamp_to_instructions(
                    thread.instructions,
                    data.timezone if data.timezone else thread.timezone,
                ),
            )
        elif thread.version == 3:
            tasks_to_run = []

            async def empty_file_list() -> list[models.File]:
                return []

            if data.code_interpreter_file_ids:
                tasks_to_run.append(
                    models.File.get_all_by_file_id(
                        request.state["db"], data.code_interpreter_file_ids
                    )
                )
            else:
                tasks_to_run.append(empty_file_list())  # placeholder

            if data.file_search_file_ids:
                tasks_to_run.append(
                    models.File.get_all_by_file_id(
                        request.state["db"], data.file_search_file_ids
                    )
                )
            else:
                tasks_to_run.append(empty_file_list())  # placeholder

            (
                code_interpreter_files,
                file_search_files,
            ) = await asyncio.gather(*tasks_to_run)

            [
                is_supervisor_check,
                ci_all_files,
                prev_output_sequence,
            ] = await asyncio.gather(
                request.state["authz"].check(
                    [
                        (
                            f"user:{request.state['session'].user.id}",
                            "supervisor",
                            f"class:{class_id}",
                        ),
                    ]
                ),
                models.Thread.get_code_interpreter_file_obj_ids_including_assistant(
                    request.state["db"], thread.id, asst.id
                ),
                models.Thread.get_max_output_sequence(request.state["db"], thread.id),
            )

            is_supervisor = is_supervisor_check[0]

            show_reasoning_summaries = is_supervisor or (
                asst and not asst.hide_reasoning_summaries
            )
            show_file_search_queries = is_supervisor or (
                asst and not asst.hide_file_search_queries
            )
            show_file_search_result_quotes = is_supervisor or (
                asst and not asst.hide_file_search_result_quotes
            )
            show_file_search_document_names = is_supervisor or (
                asst and not asst.hide_file_search_document_names
            )
            show_web_search_sources = is_supervisor or (
                asst and not asst.hide_web_search_sources
            )
            show_web_search_actions = is_supervisor or (
                asst and not asst.hide_web_search_actions
            )
            show_mcp_server_call_details = is_supervisor or (
                asst and not asst.hide_mcp_server_call_details
            )

            messageContentParts: list[models.MessagePart] = []
            part_index = 0
            for part in messageContent:
                if part["type"] == "text":
                    messageContentParts.append(
                        models.MessagePart(
                            part_index=part_index,
                            type=schemas.MessagePartType.INPUT_TEXT,
                            text=part["text"],
                        )
                    )
                elif part["type"] == "image_file":
                    messageContentParts.append(
                        models.MessagePart(
                            part_index=part_index,
                            type=schemas.MessagePartType.INPUT_IMAGE,
                            input_image_file_id=part["image_file"]["file_id"],
                        )
                    )
                part_index += 1
            run_to_complete = models.Run(
                status=schemas.RunStatus.PENDING,
                thread_id=thread.id,
                creator_id=request.state["session"].user.id,
                assistant_id=asst.id,
                model=asst.model,
                reasoning_effort=asst.reasoning_effort,
                temperature=asst.temperature,
                tools_available=thread.tools_available,
                instructions=inject_timestamp_to_instructions(
                    thread.instructions,
                    data.timezone if data.timezone else thread.timezone,
                ),
                verbosity=asst.verbosity,
                messages=[
                    models.Message(
                        thread_id=thread.id,
                        output_index=prev_output_sequence + 1,
                        message_status=schemas.MessageStatus.COMPLETED,
                        role=schemas.MessageRole.USER,
                        user_id=request.state["session"].user.id,
                        content=messageContentParts,
                        file_search_attachments=file_search_files,
                        code_interpreter_attachments=code_interpreter_files,
                    )
                ],
            )

            mcp_server_tools_by_server_label: dict[str, models.MCPServerTool] = {}

            if mcp_tool_ids:
                mcp_server_tools = await models.Run.add_mcp_server_tools_return_tools(
                    request.state["db"], run_to_complete.id, mcp_tool_ids
                )
                for tool in mcp_server_tools:
                    if tool.enabled:
                        mcp_server_tools_by_server_label[tool.server_label] = tool

            request.state["db"].add(run_to_complete)
            await request.state["db"].flush()
            await request.state["db"].refresh(run_to_complete)

            assistant_vector_store_id = (
                await models.VectorStore.get_vector_store_id_by_id(
                    request.state["db"], asst.vector_store_id
                )
                if asst.vector_store_id
                else None
            )

            stream = run_response(
                openai_client,
                run=run_to_complete,
                class_id=class_id,
                file_names=file_names,
                assistant_vector_store_id=assistant_vector_store_id,
                thread_vector_store_id=thread_vector_store_id,
                attached_file_search_file_ids=data.file_search_file_ids or [],
                code_interpreter_file_ids=ci_all_files,
                mcp_server_tools_by_server_label=mcp_server_tools_by_server_label,
                show_reasoning_summaries=show_reasoning_summaries,
                show_file_search_queries=show_file_search_queries,
                show_file_search_result_quotes=show_file_search_result_quotes,
                show_file_search_document_names=show_file_search_document_names,
                show_web_search_sources=show_web_search_sources,
                show_web_search_actions=show_web_search_actions,
                show_mcp_server_call_details=show_mcp_server_call_details,
                user_auth=request.state["auth_user"],
                anonymous_user_auth=request.state["anonymous_session_token_auth"],
                anonymous_link_auth=request.state["anonymous_share_token_auth"],
                anonymous_session_id=request.state["anonymous_session_id"],
                anonymous_link_id=request.state["anonymous_link_id"],
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid thread version",
            )
    except HTTPException:
        raise
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
async def publish_thread(class_id: str, thread_id: str, request: StateRequest):
    thread = await models.Thread.get_by_id(request.state["db"], int(thread_id))
    thread.private = False
    request.state["db"].add(thread)
    await request.state["authz"].write_safe(
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
async def unpublish_thread(class_id: str, thread_id: str, request: StateRequest):
    thread = await models.Thread.get_by_id(request.state["db"], int(thread_id))
    thread.private = True
    request.state["db"].add(thread)
    await request.state["authz"].write_safe(
        revoke=[(f"class:{class_id}#member", "can_view", f"thread:{thread_id}")]
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/thread/{thread_id}/file/{file_id}",
    dependencies=[
        Depends(Authz("can_participate", "thread:{thread_id}")),
    ],
    response_model=schemas.GenericStatus,
)
async def remove_file_from_thread(
    class_id: str,
    thread_id: str,
    file_id: str,
    request: StateRequest,
    openai_client: OpenAIClient,
):
    try:
        await models.File.delete_by_file_id(request.state["db"], file_id)
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
    class_id: str, thread_id: str, request: StateRequest, openai_client: OpenAIClient
):
    thread = await models.Thread.get_by_id_with_users_voice_mode(
        request.state["db"], int(thread_id)
    )
    # Detach the vector store from the thread and delete it
    vector_store_obj_id = None
    file_ids_to_delete = []
    if thread.vector_store_id:
        vector_store_id = thread.vector_store_id
        thread.vector_store_id = None
        # Keep the OAI vector store ID for deletion
        result_vector = await delete_vector_store_db_returning_file_ids(
            request.state["db"], vector_store_id
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
    result_ci = await request.state["db"].execute(stmt)
    file_ids_to_delete.extend([row[0] for row in result_ci.fetchall()])

    # Remove any image files associations with the thread
    stmt = (
        delete(models.image_file_thread_association)
        .where(models.image_file_thread_association.c.thread_id == int(thread.id))
        .returning(models.image_file_thread_association.c.file_id)
    )
    result_image = await request.state["db"].execute(stmt)
    file_ids_to_delete.extend([row[0] for row in result_image.fetchall()])

    revokes = [(f"class:{class_id}", "parent", f"thread:{thread_id}")] + [
        (f"user:{u.id}", "party", f"thread:{thread_id}") for u in thread.users
    ]

    if not thread.private:
        revokes.append(
            (f"class:{class_id}#member", "can_view", f"thread:{thread.id}"),
        )

    if thread.voice_mode_recording:
        try:
            await config.audio_store.store.delete_file(
                key=thread.voice_mode_recording.recording_id
            )
            await models.VoiceModeRecording.delete(
                request.state["db"], thread.voice_mode_recording.id
            )
        except Exception as e:
            logger.exception(
                "Error deleting voice mode recording for thread %s: %s",
                thread.id,
                e,
            )

    # Keep the OAI thread ID for deletion
    thread_obj_id = thread.thread_id
    thread_version = thread.version
    await thread.delete(request.state["db"])

    # Delete vector store as late as possible to avoid orphaned thread
    if vector_store_obj_id:
        await delete_vector_store_oai(openai_client, vector_store_obj_id)

    if thread_version <= 2:
        try:
            await openai_client.beta.threads.delete(thread_obj_id)
        except openai.NotFoundError:
            pass
        except openai.BadRequestError as e:
            raise HTTPException(
                400, get_details_from_api_error(e, "OpenAI rejected this request")
            )

    # clean up grants
    await request.state["authz"].write_safe(revoke=revokes)
    return {"status": "ok"}


@v1.post(
    "/class/{class_id}/file",
    dependencies=[Depends(Authz("can_upload_class_files", "class:{class_id}"))],
    response_model=schemas.File,
)
async def create_file(
    class_id: str,
    request: StateRequest,
    upload: UploadFile,
    openai_client: OpenAIClient,
):
    if upload.size > config.upload.class_file_max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size is {humanize.naturalsize(config.upload.private_file_max_size)}.",
        )

    return await handle_create_file(
        request.state["db"],
        request.state["authz"],
        openai_client,
        upload=upload,
        class_id=int(class_id),
        uploader_id=request.state["session"].user.id,
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
    request: StateRequest,
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
        request.state["db"],
        request.state["authz"],
        openai_client,
        upload=upload,
        class_id=int(class_id),
        uploader_id=request.state["session"].user.id,
        private=True,
        purpose=purpose,
        use_image_descriptions=use_image_descriptions,
        user_auth=request.state["auth_user"],
        anonymous_user_auth=request.state["anonymous_session_token_auth"],
        anonymous_link_auth=request.state["anonymous_share_token_auth"],
        anonymous_session_id=request.state["anonymous_session_id"],
        anonymous_link_id=request.state["anonymous_link_id"],
    )


@v1.delete(
    "/class/{class_id}/file/{file_id}",
    dependencies=[Depends(Authz("can_delete", "class_file:{file_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_file(
    class_id: str, file_id: str, request: StateRequest, openai_client: OpenAIClient
):
    try:
        await handle_delete_file(
            request.state["db"],
            request.state["authz"],
            openai_client,
            int(file_id),
            int(class_id),
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
    request: StateRequest,
    openai_client: OpenAIClient,
):
    try:
        await handle_delete_file(
            request.state["db"],
            request.state["authz"],
            openai_client,
            int(file_id),
            int(class_id),
        )
    except FileNotFoundException:
        raise HTTPException(404, "File not found!")
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/files",
    dependencies=[Depends(Authz("member", "class:{class_id}"))],
    response_model=schemas.Files,
)
async def list_files(class_id: str, request: StateRequest):
    ids = await request.state["authz"].list(
        f"user:{request.state['session'].user.id}", "can_view", "class_file"
    )
    class_ids = await request.state["authz"].list(
        f"class:{class_id}",
        "parent",
        "class_file",
    )

    file_ids = list(set(ids) & set(class_ids))
    files = await models.File.get_all_by_id(request.state["db"], file_ids)
    return {"files": files}


@v1.get(
    "/class/{class_id}/assistants",
    dependencies=[Depends(Authz("can_view_assistants", "class:{class_id}"))],
    response_model=schemas.Assistants,
)
async def list_assistants(class_id: str, request: StateRequest):
    # Only return assistants that are in the class and are visible to the current user.
    all_for_class = await models.Assistant.get_by_class_id(
        request.state["db"], int(class_id)
    )
    filters = await request.state["authz"].check(
        [
            (
                request.state["auth_user"]
                if not request.state["is_anonymous"]
                else request.state["anonymous_share_token_auth"],
                "can_view",
                f"assistant:{a.id}",
            )
            for a in all_for_class
        ]
    )
    assts = [a for a, f in zip(all_for_class, filters) if f]

    creator_ids = {a.creator_id for a in assts}
    creators = await models.User.get_all_by_id(request.state["db"], list(creator_ids))
    creator_perms = await request.state["authz"].check(
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
    has_elevated_perm_check = await request.state["authz"].check(
        [
            (
                request.state["auth_user"]
                if not request.state["is_anonymous"]
                else request.state["anonymous_share_token_auth"],
                "can_edit",
                f"assistant:{asst.id}",
            )
            for asst in assts
        ]
    )
    is_class_supervisor = await request.state["authz"].test(
        f"user:{request.state['session'].user.id}",
        "supervisor",
        f"class:{class_id}",
    )
    for asst, has_elevated_permissions in zip(assts, has_elevated_perm_check):
        cur_asst = schemas.Assistant.model_validate(asst)

        if not has_elevated_permissions:
            cur_asst.notes = None

            if asst.hide_prompt:
                cur_asst.instructions = ""

        # For now, "endorsed" creators are published assistants that were
        # created by a teacher or admin.
        #
        # TODO(jnu): separate this into an explicit category where teachers
        # can mark any public assistant as "endorsed."
        # https://github.com/stanford-policylab/pingpong/issues/226
        if asst.published and asst.creator_id in endorsed_creators:
            cur_asst.endorsed = True

        if is_class_supervisor:
            cur_asst.share_links = await models.AnonymousLink.get_by_assistant_id(
                request.state["db"], asst.id
            )

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
    request: StateRequest,
    openai_client: OpenAIClient,
):
    class_id_int = int(class_id)
    creator_id = request.state["session"].user.id

    class_models_response = schemas.AssistantModels.model_validate(
        await list_class_models(
            class_id=class_id, request=request, openai_client=openai_client
        )
    )
    class_models = class_models_response.models

    model_record = next(
        (model for model in class_models if model.id == req.model), None
    )

    # Check if model is available for use in this class and that the model is not hidden
    if not model_record or model_record.hide_in_model_selector:
        raise HTTPException(
            status_code=400,
            detail=f"Model {req.model} is not available for use.",
        )

    # For now, allow chat mode models to be used in lecture video assistants
    # TODO: Introduce lecture_video type in AssistantModelDict.type
    _interaction_mode = (
        schemas.InteractionMode.CHAT
        if req.interaction_mode is schemas.InteractionMode.LECTURE_VIDEO
        else req.interaction_mode
    )

    # Check that the model supports the interaction mode
    if model_record.type != _interaction_mode:
        raise HTTPException(
            status_code=400,
            detail=f"Model {req.model} is not available for use in {req.interaction_mode} mode.",
        )

    # Check that the model supports the assistant version
    if req.create_classic_assistant and not model_record.supports_classic_assistants:
        raise HTTPException(
            status_code=400,
            detail=f"Model {req.model} does not support classic assistants.",
        )

    if (
        not req.create_classic_assistant
        and not model_record.supports_next_gen_assistants
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Model {req.model} does not support next generation assistants.",
        )

    reasoning_effort_map = get_reasoning_effort_map(model_record.id)
    if (
        req.reasoning_effort is not None
        and req.reasoning_effort not in reasoning_effort_map
    ):
        raise HTTPException(
            400,
            f"Reasoning effort is not supported for model {model_record.name}.",
        )

    if (
        req.reasoning_effort == -1
        and req.tools
        and len(req.tools) > 0
        and "minimal" in reasoning_effort_map.values()
    ):
        raise HTTPException(
            400,
            "You cannot use tools when the reasoning effort is set to 'Minimal'. Please select a higher reasoning effort level.",
        )

    if req.verbosity is not None and not model_record.supports_verbosity:
        raise HTTPException(
            400,
            "The selected model does not support verbosity settings. Please select a different model or remove the verbosity setting.",
        )

    # Check that the model is not admin-only
    if not await request.state["authz"].test(
        f"user:{creator_id}",
        "admin",
        f"class:{class_id}",
    ):
        if req.model in ADMIN_ONLY_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"Model {req.model} is not available for use.",
            )

    # Only admins can create an assistant in Lecture video mode
    if req.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO:
        if not await request.state["authz"].test(
            f"user:{creator_id}",
            "admin",
            f"class:{class_id}",
        ):
            raise HTTPException(
                status_code=403,
                detail="Only class administrators can create assistants in Lecture video mode.",
            )
    if req.published:
        if not await request.state["authz"].test(
            f"user:{creator_id}", "can_publish_assistants", f"class:{class_id}"
        ):
            raise HTTPException(403, "You lack permission to publish an assistant.")

        class_ = await models.Class.get_by_id(request.state["db"], int(class_id))

    class_ = await models.Class.get_by_id(request.state["db"], class_id_int)
    if not class_:
        raise HTTPException(
            status_code=404,
            detail=f"Associated class {class_id} not found.",
        )

    # Check Azure compatibility for lecture video mode
    if req.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO and (
        class_.api_key_obj and class_.api_key_obj.provider == "azure"
    ):
        raise HTTPException(
            status_code=400,
            detail="Assistants in Lecture video mode do not support Azure OpenAI. Please select a different interaction mode or use another group.",
        )

    assistant_version = 2
    if req.interaction_mode == schemas.InteractionMode.VOICE:
        # Voice mode assistants are only supported in version 2
        assistant_version = 2
    elif req.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO:
        # Lecture video assistants require Version 3
        assistant_version = 3
    else:
        if (
            class_.api_key_obj
            and class_.api_key_obj.provider == "openai"
            and not req.create_classic_assistant
        ):
            assistant_version = 3
        elif (
            not class_.api_key_obj
            and class_.api_key
            and not req.create_classic_assistant
        ):
            assistant_version = 3
        else:
            assistant_version = 2
    del req.create_classic_assistant

    # Check that the class is not private if user information should be recorded
    if class_.private and (
        "should_record_user_information" in req.model_fields_set
        and req.should_record_user_information
    ):
        raise HTTPException(
            status_code=400,
            detail="This class is private and does not allow recording user information.",
        )
    if req.hide_file_search_document_names and not req.hide_file_search_result_quotes:
        raise HTTPException(
            status_code=400,
            detail="Cannot hide document names while showing result quotes. Please enable 'Hide File Search Result Quotes from Members' or disable 'Completely Hide File Search Results from Members'.",
        )

    if req.hide_web_search_actions and not req.hide_web_search_sources:
        raise HTTPException(
            status_code=400,
            detail="Cannot hide web search actions while showing sources. Please enable 'Hide Web Search Sources from Members' or disable 'Completely Hide Web Search Actions from Members'.",
        )

    uses_web_search = {"type": "web_search"} in req.tools
    if uses_web_search and not model_record.supports_web_search:
        raise HTTPException(
            status_code=400,
            detail="The selected model does not support Web Search. Please select a different model or remove the Web Search tool.",
        )

    uses_mcp_server = {"type": "mcp_server"} in req.tools
    if uses_mcp_server and not model_record.supports_mcp_server:
        raise HTTPException(
            status_code=400,
            detail="The selected model does not support MCP Servers. Please select a different model or remove the MCP Server tool.",
        )
    if uses_mcp_server and assistant_version <= 2:
        raise HTTPException(
            status_code=400,
            detail="Classic Assistants do not support MCP Server tools. To use MCP Servers, create a Next-Gen Assistant.",
        )

    # Validate MCP servers - auth_type must match provided credentials
    for mcp_input in req.mcp_servers:
        if (
            mcp_input.auth_type == schemas.MCPAuthType.TOKEN
            and not mcp_input.authorization_token
        ):
            raise HTTPException(
                status_code=400,
                detail=f"MCP server '{mcp_input.server_url}' has auth_type 'token' but no authorization_token provided.",
            )
        if mcp_input.auth_type == schemas.MCPAuthType.HEADER and not mcp_input.headers:
            raise HTTPException(
                status_code=400,
                detail=f"MCP server '{mcp_input.server_url}' has auth_type 'header' but no headers provided.",
            )

    if uses_web_search and assistant_version <= 2:
        raise HTTPException(
            status_code=400,
            detail="Classic Assistants do not support Web Search capabilities. To use Web Search, create a Next-Gen Assistant.",
        )

    tool_resources: ToolResources = {}
    vector_store_object_id = None
    uses_voice = req.interaction_mode == schemas.InteractionMode.VOICE
    is_video = req.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO

    if req.file_search_file_ids:
        if uses_voice:
            raise HTTPException(
                status_code=400,
                detail="File search is not supported in Voice mode.",
            )
        vector_store_id, vector_store_object_id = await create_vector_store(
            request.state["db"],
            openai_client,
            class_id,
            req.file_search_file_ids,
            type=schemas.VectorStoreType.ASSISTANT,
        )
        tool_resources["file_search"] = {"vector_store_ids": [vector_store_id]}

    del req.file_search_file_ids

    if req.code_interpreter_file_ids:
        if uses_voice:
            raise HTTPException(
                status_code=400,
                detail="Code interpreter is not supported in Voice mode.",
            )
        tool_resources["code_interpreter"] = {"file_ids": req.code_interpreter_file_ids}

    lecture_video_object_id = None
    if is_video:
        if not req.lecture_video_key:
            raise HTTPException(
                status_code=400,
                detail="Specifying a lecture video is required for lecture video assistants.",
            )
        if not config.video_store:
            raise HTTPException(status_code=404, detail="No Video Store exists.")

        try:
            lecture_video = await config.video_store.store.get_or_create(
                request.state["db"],
                req.lecture_video_key,
                request.state["session"].user.id,
            )
        except VideoStoreError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error saving lecture video: {e.detail or str(e)}",
            ) from e
        except TypeError as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid lecture video: {e}"
            ) from e
        except Exception as e:
            logger.exception("Unexpected error saving lecture video")
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while saving the lecture video. Please try again later.",
            ) from e
        lecture_video_object_id = lecture_video.id

    if assistant_version <= 2:
        try:
            if uses_voice:
                _model = "gpt-4o"
            else:
                _model = (
                    get_azure_model_deployment_name_equivalent(req.model)
                    if isinstance(openai_client, openai.AsyncAzureOpenAI)
                    else req.model
                )

            reasoning_effort_map = get_reasoning_effort_map(model_record.id)
            reasoning_effort = (
                reasoning_effort_map.get(req.reasoning_effort)
                if req.reasoning_effort is not None
                else None
            )
            reasoning_extra_body = (
                {"reasoning_effort": reasoning_effort}
                if reasoning_effort is not None
                else {}
            )

            # Set default temperature based on the interaction mode
            # This is to ensure that the temperature is set
            # appropriately for the mode.
            if "temperature" not in req.model_fields_set or req.temperature is None:
                if uses_voice:
                    req.temperature = 0.8
                else:
                    req.temperature = 0.2

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
    elif assistant_version == 3:
        responses_api_transition_logger.debug(
            "Creating a Version 3 assistant; skipping creation of OpenAI Assistants API object."
        )
        new_asst = None
    else:
        raise HTTPException(400, "Invalid assistant version")

    try:
        deleted_private_files = req.deleted_private_files or []
        del req.deleted_private_files
        mcp_servers_input = req.mcp_servers or []
        del req.mcp_servers
        del req.lecture_video_key

        asst = await models.Assistant.create(
            request.state["db"],
            req,
            class_id=class_id_int,
            user_id=creator_id,
            assistant_id=new_asst.id if new_asst else None,
            vector_store_id=vector_store_object_id,
            lecture_video_id=lecture_video_object_id,
            version=assistant_version,
        )

        # Delete private files uploaded but not attached to the assistant
        files_to_delete = await models.File.get_files_not_used_by_assistant(
            request.state["db"], asst.id, deleted_private_files
        )
        await handle_delete_files(
            request.state["db"],
            request.state["authz"],
            openai_client,
            files_to_delete,
            class_id=int(class_id),
        )

        # Create MCP servers and associate with assistant
        if mcp_servers_input:

            async def create_mcp_server(
                mcp_input: schemas.MCPServerToolInput, assistant_id: int
            ) -> models.MCPServerTool:
                headers_json = None
                authorization_token = None
                if mcp_input.auth_type == schemas.MCPAuthType.HEADER:
                    headers_json = (
                        json.dumps(mcp_input.headers) if mcp_input.headers else None
                    )
                elif mcp_input.auth_type == schemas.MCPAuthType.TOKEN:
                    authorization_token = mcp_input.authorization_token

                tool = await models.MCPServerTool.create(
                    request.state["db"],
                    {
                        "display_name": mcp_input.display_name,
                        "server_url": mcp_input.server_url_str,
                        "headers": headers_json,
                        "authorization_token": authorization_token,
                        "description": mcp_input.description,
                        "enabled": mcp_input.enabled,
                        "created_by_user_id": request.state["session"].user.id,
                    },
                )

                # Log which user created the MCP server tool and some basic info
                logger.info(
                    f"User {request.state['session'].user.id} created MCP server tool {tool.server_label} for assistant {assistant_id} with URL {tool.server_url} and display name '{tool.display_name}'"
                )
                return tool

            mcp_servers = []
            for mcp_input in mcp_servers_input:
                mcp_servers.append(await create_mcp_server(mcp_input, asst.id))
            await models.Assistant.synchronize_assistant_mcp_server_tools(
                request.state["db"],
                asst.id,
                [s.id for s in mcp_servers],
                skip_delete=True,
            )

        grants = [
            (f"class:{class_id}", "parent", f"assistant:{asst.id}"),
            (f"user:{creator_id}", "owner", f"assistant:{asst.id}"),
        ]

        if req.published:
            grants.append(
                (f"class:{class_id}#member", "can_view", f"assistant:{asst.id}"),
            )

        await request.state["authz"].write(grant=grants)

        return asst
    except Exception as e:
        if vector_store_object_id:
            await openai_client.vector_stores.delete(vector_store_id)
        if new_asst and new_asst.id:
            await openai_client.beta.assistants.delete(new_asst.id)
        raise e


@v1.post(
    "/class/{class_id}/assistant_instructions",
    dependencies=[Depends(Authz("can_create_assistants", "class:{class_id}"))],
    response_model=schemas.AssistantInstructionsPreviewResponse,
)
async def preview_assistant_instructions(
    class_id: str,
    req: schemas.AssistantInstructionsPreviewRequest,
    request: StateRequest,
):
    return {
        "instructions_preview": format_instructions(
            req.instructions,
            use_latex=False,
            use_image_descriptions=False,
            user_id=request.state["session"].user.id,
            thread_id=f"preview_{uuid.uuid4()}",
        )
    }


def _classes_share_api_key(src: models.Class | None, tgt: models.Class | None) -> bool:
    """
    Return True if both classes have the same configured API key or key id.
    """
    if not src or not tgt:
        return False
    if src.api_key_id and tgt.api_key_id:
        return src.api_key_id == tgt.api_key_id
    if src.api_key and tgt.api_key:
        return src.api_key == tgt.api_key
    return False


@v1.post(
    "/class/{class_id}/assistant/{assistant_id}/copy",
    dependencies=[
        Depends(Authz("can_edit", "assistant:{assistant_id}")),
    ],
    response_model=schemas.Assistant,
)
async def copy_assistant(
    class_id: str,
    assistant_id: str,
    request: StateRequest,
    openai_client: OpenAIClient,
    copy_options: schemas.CopyAssistantRequest | None = Body(default=None),
):
    assistant = await models.Assistant.get_by_id_with_ci_files_mcp(
        request.state["db"], int(assistant_id)
    )
    class_id_int = int(class_id)
    if not assistant or assistant.class_id != class_id_int:
        raise HTTPException(
            status_code=404,
            detail="Assistant not found",
        )
    source_class = await models.Class.get_by_id(request.state["db"], class_id_int)
    if not source_class:
        raise HTTPException(status_code=404, detail="Class not found")

    def _default_copy_name(name: str) -> str:
        suffix = " (Copy)"
        max_len = 100
        if len(name) + len(suffix) > max_len:
            name = name[: max_len - len(suffix)]
        return f"{name}{suffix}"

    target_class_id = (
        copy_options.target_class_id
        if copy_options and copy_options.target_class_id
        else class_id_int
    )

    target_class = await models.Class.get_by_id(request.state["db"], target_class_id)
    if not target_class:
        raise HTTPException(
            status_code=404,
            detail="Target class not found",
        )

    if not (source_class.api_key_id or source_class.api_key):
        raise HTTPException(
            status_code=400,
            detail="Source class has no API key configured.",
        )

    if not (target_class.api_key_id or target_class.api_key):
        raise HTTPException(
            status_code=400,
            detail="Target class has no API key configured.",
        )

    if not _classes_share_api_key(source_class, target_class):
        raise HTTPException(
            status_code=400,
            detail="Source and target classes must share the same API key to copy assistants.",
        )

    can_create_in_target = await request.state["authz"].test(
        request.state["auth_user"],
        "can_create_assistants",
        f"class:{target_class_id}",
    )
    if not can_create_in_target:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to create assistants in the target group.",
        )

    if target_class_id == class_id_int:
        target_openai_client = openai_client
    else:
        try:
            target_openai_client = await get_openai_client_by_class_id(
                request.state["db"], target_class_id
            )
        except GetOpenAIClientException as e:
            raise HTTPException(status_code=e.code or 400, detail=e.detail)

    requested_name = (
        copy_options.name.strip() if copy_options and copy_options.name else None
    )

    new_assistant = await copy_assistant_to_class(
        request.state["db"],
        request.state["authz"],
        target_openai_client,
        target_class_id,
        assistant,
        new_name=requested_name or _default_copy_name(assistant.name),
        require_published=False,
        force_private=True,
    )
    if not new_assistant:
        raise HTTPException(status_code=400, detail="Assistant could not be copied.")
    return new_assistant


@v1.post(
    "/class/{class_id}/assistant/{assistant_id}/copy/check",
    dependencies=[
        Depends(Authz("can_edit", "assistant:{assistant_id}")),
    ],
    response_model=schemas.CopyAssistantCheckResponse,
)
async def copy_assistant_check(
    class_id: str,
    assistant_id: str,
    request: StateRequest,
    copy_options: schemas.CopyAssistantRequest,
):
    assistant = await models.Assistant.get_by_id(request.state["db"], int(assistant_id))
    class_id_int = int(class_id)
    if not assistant or assistant.class_id != class_id_int:
        raise HTTPException(
            status_code=404,
            detail="Assistant not found",
        )
    source_class = await models.Class.get_by_id(request.state["db"], class_id_int)
    if not source_class:
        raise HTTPException(status_code=404, detail="Class not found")

    target_class_id = copy_options.target_class_id or class_id_int
    target_class = await models.Class.get_by_id(request.state["db"], target_class_id)
    if not target_class:
        raise HTTPException(
            status_code=404,
            detail="Target class not found",
        )

    if not (target_class.api_key_id or target_class.api_key):
        raise HTTPException(
            status_code=400,
            detail="Target class has no API key configured.",
        )

    if not (source_class.api_key_id or source_class.api_key):
        raise HTTPException(
            status_code=400,
            detail="Source class has no API key configured.",
        )

    if not _classes_share_api_key(source_class, target_class):
        raise HTTPException(
            status_code=400,
            detail="Source and target classes must share the same API key to copy assistants.",
        )

    can_create_in_target = await request.state["authz"].test(
        request.state["auth_user"],
        "can_create_assistants",
        f"class:{target_class_id}",
    )
    if not can_create_in_target:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to create assistants in the target group.",
        )

    return schemas.CopyAssistantCheckResponse(allowed=True)


@v1.post(
    "/class/{class_id}/assistant/{assistant_id}/share",
    dependencies=[
        Depends(
            Authz("can_edit", "assistant:{assistant_id}"),
        ),
        Depends(Authz("can_share_assistants", "class:{class_id}")),
    ],
    response_model=schemas.GenericStatus,
)
async def share_assistant(
    class_id: str,
    assistant_id: str,
    request: StateRequest,
):
    """
    Create an anonymous share of an assistant with the class.
    """
    asst = await models.Assistant.get_by_id(request.state["db"], int(assistant_id))
    if not asst:
        raise HTTPException(
            status_code=404,
            detail=f"Assistant {assistant_id} not found.",
        )

    if not asst.published:
        raise HTTPException(
            status_code=400,
            detail="This assistant is not published and cannot be shared.",
        )

    if asst.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO:
        raise HTTPException(
            status_code=403, detail="Lecture Video assistants cannot be shared."
        )

    # Create a new anonymous link for the assistant
    share_link = await models.AnonymousLink.create(
        request.state["db"],
        share_token=str(uuid.uuid7()),
        assistant_id=asst.id,
    )

    await models.User.create_anonymous_user(
        request.state["db"],
        anonymous_link_id=share_link.id,
    )

    auth_user = f"anonymous_link:{share_link.share_token}"
    await request.state["authz"].write_safe(
        grant=[
            (auth_user, "can_view", f"class:{class_id}"),
            (
                auth_user,
                "can_create_thread",
                f"class:{class_id}",
            ),
            (auth_user, "can_view", f"assistant:{assistant_id}"),
        ]
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}/share/{share_id}",
    dependencies=[
        Depends(
            Authz("can_edit", "assistant:{assistant_id}"),
        ),
        Depends(Authz("can_share_assistants", "class:{class_id}")),
    ],
    response_model=schemas.GenericStatus,
)
async def unshare_assistant(
    class_id: str,
    assistant_id: str,
    share_id: str,
    request: StateRequest,
):
    """
    Remove an anonymous share of an assistant with the class.
    """
    asst, share_link = await asyncio.gather(
        models.Assistant.get_by_id(request.state["db"], int(assistant_id)),
        models.AnonymousLink.get_by_id(request.state["db"], int(share_id)),
    )
    if not asst:
        raise HTTPException(
            status_code=404,
            detail=f"Assistant {assistant_id} not found.",
        )

    if not share_link:
        raise HTTPException(
            status_code=404,
            detail="Share link not found.",
        )

    if share_link.assistant.id != asst.id:
        raise HTTPException(
            status_code=400,
            detail="This share link does not belong to the specified assistant.",
        )

    if not share_link.active:
        raise HTTPException(
            status_code=400,
            detail="This share link is already inactive.",
        )

    auth_user = f"anonymous_link:{share_link.share_token}"

    await models.AnonymousLink.revoke(
        request.state["db"],
        share_link.id,
    )
    await request.state["authz"].write_safe(
        revoke=[
            (auth_user, "can_view", f"class:{class_id}"),
            (
                auth_user,
                "can_create_thread",
                f"class:{class_id}",
            ),
            (auth_user, "can_view", f"assistant:{assistant_id}"),
        ]
    )
    return {"status": "ok"}


@v1.put(
    "/class/{class_id}/assistant/{assistant_id}/share/{share_id}",
    dependencies=[
        Depends(
            Authz("can_edit", "assistant:{assistant_id}"),
        ),
        Depends(Authz("can_share_assistants", "class:{class_id}")),
    ],
    response_model=schemas.GenericStatus,
)
async def update_assistant_share_name(
    class_id: str,
    assistant_id: str,
    share_id: str,
    req: schemas.UpdateAssistantShareNameRequest,
    request: StateRequest,
):
    """
    Update the name of an anonymous share of an assistant with the class.
    """
    share_link = await models.AnonymousLink.get_by_id(
        request.state["db"], int(share_id)
    )

    if not share_link:
        raise HTTPException(
            status_code=404,
            detail="Share link not found.",
        )

    share_link.name = req.name
    request.state["db"].add(share_link)
    await request.state["db"].flush()

    return {"status": "ok"}


@v1.put(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[Depends(Authz("can_edit", "assistant:{assistant_id}"))],
    response_model=schemas.Assistant,
)
async def update_assistant(
    class_id: str,
    assistant_id: str,
    req: schemas.UpdateAssistant,
    request: StateRequest,
    openai_client: OpenAIClient,
):
    # Get the existing assistant.
    asst = await models.Assistant.get_by_id_with_ci_files_mcp(
        request.state["db"], int(assistant_id)
    )
    grants = list[Relation]()
    revokes = list[Relation]()

    # Users without publish permission can't toggle the published status of assistants.
    is_toggling_publish_status = (
        "published" in req.model_fields_set
        and req.published is not None
        and (
            (req.published is True and asst.published is None)
            or (req.published is False and asst.published is not None)
        )
    )

    if is_toggling_publish_status:
        if not await request.state["authz"].test(
            f"user:{request.state['session'].user.id}",
            "can_publish",
            f"assistant:{assistant_id}",
        ):
            raise HTTPException(
                status_code=403,
                detail="You are not allowed to toggle the published status of assistants for this class.",
            )

    if not req.model_dump():
        return asst

    interaction_mode = (
        req.interaction_mode
        if (
            "interaction_mode" in req.model_fields_set
            and req.interaction_mode is not None
        )
        else schemas.InteractionMode(asst.interaction_mode)
    )

    # Only Administrators can edit locked assistants or Lecture Video asssistants
    if (
        asst.locked and req.model_fields_set != {"published", "use_image_descriptions"}
    ) or interaction_mode == schemas.InteractionMode.LECTURE_VIDEO:
        if not await request.state["authz"].test(
            f"user:{request.state['session'].user.id}",
            "admin",
            f"class:{class_id}",
        ):
            raise HTTPException(
                403,
                "This assistant is locked and cannot be edited. Please create a new assistant if you need to make changes."
                if (
                    asst.locked
                    and req.model_fields_set != {"published", "use_image_descriptions"}
                )
                else "Only class administrators can create assistants in Lecture Video mode.",
            )

    class_ = await models.Class.get_by_id(request.state["db"], int(class_id))
    if not class_:
        raise HTTPException(
            status_code=404,
            detail=f"Associated class {class_id} not found.",
        )

    # Check that the class is not private if user information should be recorded
    if class_.private and (
        "should_record_user_information" in req.model_fields_set
        and req.should_record_user_information is not None
        and req.should_record_user_information
    ):
        raise HTTPException(
            status_code=400,
            detail="This class is private and does not allow recording user information.",
        )
    openai_update: dict[str, Any] = {}
    tool_resources: ToolResources = {}
    update_tool_resources = False
    update_instructions = False
    uses_voice = interaction_mode == schemas.InteractionMode.VOICE
    is_video = interaction_mode == schemas.InteractionMode.LECTURE_VIDEO

    # Prevent updating existing assistants to lecture video mode
    if is_video and asst.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO:
        raise HTTPException(
            status_code=400,
            detail="Cannot convert existing assistants to Lecture Video mode. Please create a new assistant.",
        )

    # Prevent changing lecture video assistants to other interaction modes
    if not is_video and asst.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO:
        raise HTTPException(
            status_code=400,
            detail="Assistants in Lecture Video mode cannot be switched to another interaction mode. Please create a new assistant.",
        )
    convert_to_next_gen_requested = (
        "convert_to_next_gen" in req.model_fields_set
        and req.convert_to_next_gen is not None
    )
    convert_to_next_gen = (
        "convert_to_next_gen" in req.model_fields_set
        and req.convert_to_next_gen is True
    )
    if (
        convert_to_next_gen_requested
        and interaction_mode == schemas.InteractionMode.LECTURE_VIDEO
    ):
        raise HTTPException(
            status_code=400,
            detail="Assistant version conversions are not supported in Lecture Video mode.",
        )

    # Reinforce assistant version defaults:
    # 1. Azure OpenAI only supports classic assistants (v2).
    # 2. Existing classic assistants remain classic by default.
    # 3. Assistant version changes only happen when explicitly requested.
    if isinstance(openai_client, openai.AsyncAzureOpenAI):
        if convert_to_next_gen:
            raise HTTPException(
                status_code=400,
                detail="Next-Gen assistants are not available for your AI Provider.",
            )
        asst.version = 2
    elif is_video:
        asst.version = 3
    else:
        has_openai_key = bool(
            class_.api_key_obj and class_.api_key_obj.provider == "openai"
        ) or bool(not class_.api_key_obj and class_.api_key)
        if convert_to_next_gen:
            if not has_openai_key:
                raise HTTPException(
                    status_code=400,
                    detail="Next-Gen assistants are not available for your AI Provider.",
                )
            asst.version = 3
        elif convert_to_next_gen_requested:
            asst.version = 2
        else:
            asst.version = 3 if asst.version == 3 else 2

    # If the interaction mode is changing, and the user did not specify a
    # temperature, set a default temperature based on the interaction mode
    # This is to ensure that the temperature is set appropriately for the mode.
    if interaction_mode != asst.interaction_mode and (
        "temperature" not in req.model_fields_set or req.temperature is None
    ):
        if uses_voice:
            openai_update["temperature"] = 0.8
            asst.temperature = 0.8
        else:
            openai_update["temperature"] = 0.2
            asst.temperature = 0.2

    model_record = None
    # For now, allow chat mode models to be used in lecture video assistants
    # TODO: Introduce lecture_video type in AssistantModelDict.type
    _interaction_mode = (
        schemas.InteractionMode.CHAT
        if interaction_mode is schemas.InteractionMode.LECTURE_VIDEO
        else interaction_mode
    )

    # Check that the model is available
    if "model" in req.model_fields_set and req.model is not None:
        _model = None
        _model = (
            get_azure_model_deployment_name_equivalent(req.model)
            if isinstance(openai_client, openai.AsyncAzureOpenAI)
            else req.model
        )

        if _model != asst.model:
            class_models_response = schemas.AssistantModels.model_validate(
                await list_class_models(
                    class_id=class_id, request=request, openai_client=openai_client
                )
            )
            class_models = class_models_response.models

            model_record = next(
                (model for model in class_models if model.id == req.model), None
            )

            if not model_record or model_record.hide_in_model_selector:
                raise HTTPException(
                    status_code=400,
                    detail=f"Model {req.model} is not available for use.",
                )

            # Check that the model supports the interaction mode
            if model_record.type != _interaction_mode:
                raise HTTPException(
                    status_code=400,
                    detail=f"Model {req.model} is not available for use in {interaction_mode} mode.",
                )

            # Check that the model is not admin-only
            if not await request.state["authz"].test(
                f"user:{request.state['session'].user.id}",
                "admin",
                f"class:{class_id}",
            ):
                if model_record.id in ADMIN_ONLY_MODELS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Model {req.model} is not available for use.",
                    )
        else:
            model_record_req = KNOWN_MODELS.get(asst.model)
            if model_record_req and not model_record:
                model_record = schemas.AssistantModel(
                    **model_record_req,
                    id=asst.model,
                    created=utcnow(),
                    updated=utcnow(),
                    owner="",
                )

        # Override the assistant model we send to OpenAI
        # when using voice mode
        if uses_voice:
            _model = "gpt-4o"
        openai_update["model"] = _model
        asst.model = req.model

    else:
        _model = (
            get_original_model_name_by_azure_equivalent(asst.model)
            if isinstance(openai_client, openai.AsyncAzureOpenAI)
            else asst.model
        )

        class_models_response = schemas.AssistantModels.model_validate(
            await list_class_models(
                class_id=class_id, request=request, openai_client=openai_client
            )
        )
        class_models = class_models_response.models

        model_record = next(
            (model for model in class_models if model.id == _model), None
        )

        # Check that the model supports the interaction mode
        if not model_record or model_record.type != _interaction_mode:
            raise HTTPException(
                status_code=400,
                detail=f"Model {_model} is not available for use in {interaction_mode.capitalize()} mode.",
            )

    if (
        "lecture_video_key" in req.model_fields_set
        and req.lecture_video_key is not None
    ):
        if interaction_mode != schemas.InteractionMode.LECTURE_VIDEO:
            raise HTTPException(
                status_code=400,
                detail="Lecture video key can only be set for assistants in Lecture Video mode.",
            )

        if not config.video_store:
            raise HTTPException(status_code=404, detail="No Video Store exists.")

        try:
            lecture_video = await config.video_store.store.get_or_create(
                request.state["db"],
                req.lecture_video_key,
                request.state["session"].user.id,
            )
        except VideoStoreError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error saving lecture video: {e.detail or str(e)}",
            ) from e
        except TypeError as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid lecture video: {e}"
            ) from e
        except Exception as e:
            logger.exception("Unexpected error saving lecture video")
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while saving the lecture video. Please try again later.",
            ) from e
        asst.lecture_video_id = lecture_video.id

    reasoning_effort_map = (
        get_reasoning_effort_map(model_record.id) if model_record else {}
    )

    new_reasoning_effort_body = None
    if "reasoning_effort" in req.model_fields_set:
        if (
            req.reasoning_effort is not None
            and req.reasoning_effort not in reasoning_effort_map
        ):
            raise HTTPException(
                400,
                "Reasoning effort is not supported for the selected model.",
            )
        reasoning_effort = (
            reasoning_effort_map.get(req.reasoning_effort)
            if req.reasoning_effort is not None
            else None
        )

        if (reasoning_effort == "minimal" or reasoning_effort == "none") and (
            (
                "tools" in req.model_fields_set
                and req.tools is not None
                and len(req.tools) > 0
            )
            or (
                ("tools" not in req.model_fields_set or req.tools is None)
                and (asst.tools and json.loads(asst.tools))
            )
        ):
            raise HTTPException(
                400,
                "You cannot use tools when the reasoning effort is set to 'Minimal'. Please select a higher reasoning effort level.",
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
        new_reasoning_effort_body = reasoning_extra_body
    else:
        if (
            asst.reasoning_effort is not None
            and asst.reasoning_effort == -1
            and "minimal" in reasoning_effort_map.values()
            and (
                (
                    "tools" in req.model_fields_set
                    and req.tools is not None
                    and len(req.tools) > 0
                )
                or (
                    ("tools" not in req.model_fields_set or req.tools is None)
                    and (asst.tools and json.loads(asst.tools))
                )
            )
        ):
            raise HTTPException(
                400,
                "You cannot use tools when the reasoning effort is set to 'Minimal'. Please select a higher reasoning effort level.",
            )
        if model_record:
            reasoning_effort_map = get_reasoning_effort_map(model_record.id)
            new_reasoning_effort_body = (
                {"reasoning_effort": reasoning_effort_map.get(asst.reasoning_effort)}
                if asst.reasoning_effort
                else {}
            )
        else:
            new_reasoning_effort_body = (
                {"reasoning_effort": None} if asst.reasoning_effort else {}
            )

    uses_web_search = False
    if "tools" in req.model_fields_set:
        if req.tools is None or len(req.tools) == 0:
            uses_web_search = False
        else:
            uses_web_search = {"type": "web_search"} in req.tools
    else:
        uses_web_search = (
            asst.tools is not None and {"type": "web_search"} in asst.tools
        )

    if uses_web_search and asst.version <= 2:
        raise HTTPException(
            status_code=400,
            detail="Classic Assistants do not support Web Search capabilities. To use Web Search, create a Next-Gen Assistant.",
        )

    if uses_web_search and (model_record and not model_record.supports_web_search):
        raise HTTPException(
            400,
            "The selected model does not support Web Search. Please select a different model or remove the Web Search tool.",
        )

    if uses_web_search and is_video:
        raise HTTPException(
            400,
            detail="Assistants in Lecture Video mode do not support Web Search capabilities. Please remove the Web Search tool or create a new assistant without Lecture Video mode.",
        )

    uses_mcp_server = False
    if "tools" in req.model_fields_set:
        if req.tools is not None and len(req.tools) > 0:
            uses_mcp_server = {"type": "mcp_server"} in req.tools
    else:
        uses_mcp_server = asst.tools is not None and {
            "type": "mcp_server"
        } in json.loads(asst.tools)

    if uses_mcp_server and asst.version <= 2:
        raise HTTPException(
            400,
            "Classic Assistants do not support MCP Server tools. To use MCP Servers, create a Next-Gen Assistant.",
        )

    if uses_mcp_server and (model_record and not model_record.supports_mcp_server):
        raise HTTPException(
            400,
            "The selected model does not support MCP Servers. Please select a different model or remove the MCP Server tool.",
        )

    if uses_mcp_server and is_video:
        raise HTTPException(
            400,
            detail="Assistants in Lecture Video mode do not support MCP Server tools. Please remove the MCP Server tool or create a new assistant without Lecture Video mode.",
        )

    existing_mcp_by_label = {}
    if "mcp_servers" in req.model_fields_set and req.mcp_servers:
        existing_mcp_by_label = {s.server_label: s for s in asst.mcp_server_tools}

        for mcp_input in req.mcp_servers:
            if not mcp_input.server_label:
                if (
                    mcp_input.auth_type == schemas.MCPAuthType.TOKEN
                    and not mcp_input.authorization_token
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=f"MCP server '{mcp_input.server_url_str}' has auth_type 'token' but no authorization_token provided.",
                    )
                if (
                    mcp_input.auth_type == schemas.MCPAuthType.HEADER
                    and not mcp_input.headers
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=f"MCP server '{mcp_input.server_url_str}' has auth_type 'header' but no headers provided.",
                    )
            else:
                existing_server = existing_mcp_by_label.get(mcp_input.server_label)
                if not existing_server:
                    raise HTTPException(
                        status_code=400,
                        detail=f"MCP server with label '{mcp_input.server_label}' not found.",
                    )

                if mcp_input.auth_type == schemas.MCPAuthType.TOKEN:
                    if (
                        not mcp_input.authorization_token
                        and not existing_server.authorization_token
                    ):
                        raise HTTPException(
                            status_code=400,
                            detail=f"MCP server '{mcp_input.server_label}' has auth_type 'token' but no authorization_token provided and none exists.",
                        )
                elif mcp_input.auth_type == schemas.MCPAuthType.HEADER:
                    if not mcp_input.headers:
                        raise HTTPException(
                            status_code=400,
                            detail=f"MCP server '{mcp_input.server_label}' has auth_type 'header' but no headers provided.",
                        )

    if "verbosity" in req.model_fields_set:
        if req.verbosity is not None and (
            model_record and not model_record.supports_verbosity
        ):
            raise HTTPException(
                400,
                "The selected model does not support verbosity settings. Please select a different model or remove the verbosity setting.",
            )
        asst.verbosity = req.verbosity
    else:
        if asst.verbosity is not None and (
            model_record and not model_record.supports_verbosity
        ):
            raise HTTPException(
                400,
                "The selected model does not support verbosity settings. Please remove the verbosity setting.",
            )

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
                if uses_voice:
                    raise HTTPException(
                        status_code=400,
                        detail="Code interpreter is not supported in Voice mode.",
                    )
                if is_video:
                    raise HTTPException(
                        status_code=400,
                        detail="Code interpreter is not supported in Lecture Video mode.",
                    )
                tool_resources["code_interpreter"] = {
                    "file_ids": req.code_interpreter_file_ids
                }
                asst.code_interpreter_files = await models.File.get_all_by_file_id(
                    request.state["db"], req.code_interpreter_file_ids
                )
            else:
                asst.code_interpreter_files = []

        # --------------------- File Search ---------------------
        if "file_search_file_ids" in req.model_fields_set:
            update_tool_resources = True
            if req.file_search_file_ids is not None and req.file_search_file_ids != []:
                if uses_voice:
                    raise HTTPException(
                        status_code=400,
                        detail="File search is not supported in Voice mode.",
                    )
                if is_video:
                    raise HTTPException(
                        status_code=400,
                        detail="File search is not supported in Lecture Video mode.",
                    )
                # Files will need to be stored in a vector store
                if asst.vector_store_id:
                    # Vector store already exists, update
                    vector_store_id = await sync_vector_store_files(
                        request.state["db"],
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
                        request.state["db"],
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
                        request.state["db"], id_to_delete
                    )
                    tool_resources["file_search"] = {}
    except ValueError as e:
        logger.exception("Error updating assistant files")
        raise HTTPException(
            400, f"Error updating assistant files: {e}. Please try saving again."
        )
    except Exception:
        logger.exception("Error updating assistant files")
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

    if "interaction_mode" in req.model_fields_set and req.interaction_mode is not None:
        asst.interaction_mode = req.interaction_mode

    if "hide_prompt" in req.model_fields_set and req.hide_prompt is not None:
        asst.hide_prompt = req.hide_prompt

    if (
        "assistant_should_message_first" in req.model_fields_set
        and req.assistant_should_message_first is not None
    ):
        asst.assistant_should_message_first = req.assistant_should_message_first

    if "instructions" in req.model_fields_set and req.instructions is not None:
        update_instructions = True
        if not req.instructions:
            raise HTTPException(400, "Instructions cannot be empty.")
        asst.instructions = req.instructions

    if "description" in req.model_fields_set and req.description is not None:
        asst.description = req.description

    if "notes" in req.model_fields_set and req.notes is not None:
        asst.notes = req.notes

    if "tools" in req.model_fields_set and req.tools is not None:
        openai_update["tools"] = req.tools
        asst.tools = json.dumps(req.tools)

    if "mcp_servers" in req.model_fields_set and req.mcp_servers is not None:

        async def upsert_mcp_server(mcp_input: schemas.MCPServerToolInput) -> int:
            headers_json = None
            authorization_token = None

            if mcp_input.auth_type == schemas.MCPAuthType.HEADER:
                headers_json = (
                    json.dumps(mcp_input.headers) if mcp_input.headers else None
                )
            elif mcp_input.auth_type == schemas.MCPAuthType.TOKEN:
                authorization_token = mcp_input.authorization_token

            if (
                mcp_input.server_label
                and mcp_input.server_label in existing_mcp_by_label
            ):
                existing_server = existing_mcp_by_label[mcp_input.server_label]
                has_changes = False
                if existing_server.server_url != mcp_input.server_url_str:
                    logger.info(
                        f"User {request.state['session'].user.id} updated MCP server tool URL for tool {existing_server.server_label} for assistant {assistant_id} from {existing_server.server_url} to {mcp_input.server_url_str}"
                    )
                    existing_server.server_url = mcp_input.server_url_str
                    has_changes = True
                if existing_server.description != mcp_input.description:
                    existing_server.description = mcp_input.description
                    has_changes = True
                if existing_server.enabled != mcp_input.enabled:
                    logger.info(
                        f"User {request.state['session'].user.id} updated MCP server tool enabled status for tool {existing_server.server_label} for assistant {assistant_id} from {existing_server.enabled} to {mcp_input.enabled}"
                    )
                    existing_server.enabled = mcp_input.enabled
                    has_changes = True
                if existing_server.display_name != mcp_input.display_name:
                    logger.info(
                        f"User {request.state['session'].user.id} updated MCP server tool display name for tool {existing_server.server_label} for assistant {assistant_id} from '{existing_server.display_name}' to '{mcp_input.display_name}'"
                    )
                    existing_server.display_name = mcp_input.display_name
                    has_changes = True

                if mcp_input.auth_type == schemas.MCPAuthType.NONE:
                    if (
                        existing_server.headers is not None
                        or existing_server.authorization_token is not None
                    ):
                        logger.info(
                            f"User {request.state['session'].user.id} removed authentication for MCP server tool {existing_server.server_label} for assistant {assistant_id}"
                        )
                    if existing_server.headers is not None:
                        existing_server.headers = None
                        has_changes = True
                    if existing_server.authorization_token is not None:
                        existing_server.authorization_token = None
                        has_changes = True
                elif mcp_input.auth_type == schemas.MCPAuthType.HEADER:
                    if existing_server.headers != headers_json:
                        logger.info(
                            f"User {request.state['session'].user.id} updated MCP server tool headers for tool {existing_server.server_label} for assistant {assistant_id}"
                        )
                        existing_server.headers = headers_json
                        has_changes = True
                    if existing_server.authorization_token is not None:
                        logger.info(
                            f"User {request.state['session'].user.id} switched MCP server tool {existing_server.server_label} for assistant {assistant_id} to header-based authentication, removing existing authorization token"
                        )
                        existing_server.authorization_token = None
                        has_changes = True
                elif mcp_input.auth_type == schemas.MCPAuthType.TOKEN:
                    if existing_server.headers is not None:
                        logger.info(
                            f"User {request.state['session'].user.id} switched MCP server tool {existing_server.server_label} for assistant {assistant_id} to token-based authentication, removing existing headers"
                        )
                        existing_server.headers = None
                        has_changes = True
                    if authorization_token:
                        if existing_server.authorization_token != authorization_token:
                            logger.info(
                                f"User {request.state['session'].user.id} updated MCP server tool authorization token for tool {existing_server.server_label} for assistant {assistant_id}"
                            )
                            existing_server.authorization_token = authorization_token
                            has_changes = True

                if has_changes:
                    existing_server.updated_by_user_id = request.state[
                        "session"
                    ].user.id
                    request.state["db"].add(existing_server)
                return existing_server.id
            else:
                mcp_server = await models.MCPServerTool.create(
                    request.state["db"],
                    {
                        "display_name": mcp_input.display_name,
                        "server_url": mcp_input.server_url_str,
                        "headers": headers_json,
                        "authorization_token": authorization_token,
                        "description": mcp_input.description,
                        "enabled": mcp_input.enabled,
                        "created_by_user_id": request.state["session"].user.id,
                    },
                )
                logger.info(
                    f"User {request.state['session'].user.id} created MCP server tool {mcp_server.server_label} for assistant {assistant_id} with URL {mcp_server.server_url} and display name '{mcp_server.display_name}'"
                )
                return mcp_server.id

        mcp_server_ids = []
        for mcp_input in req.mcp_servers:
            mcp_server_ids.append(await upsert_mcp_server(mcp_input))
        await request.state["db"].flush()
        await models.Assistant.synchronize_assistant_mcp_server_tools(
            request.state["db"], asst.id, list(mcp_server_ids)
        )
        await models.Thread.update_mcp_server_tools_available(
            request.state["db"],
            asst.id,
            list(mcp_server_ids),
            asst.version,
            asst.interaction_mode,
        )
    elif "tools" in req.model_fields_set and (
        req.tools is None or {"type": "mcp_server"} not in req.tools
    ):
        await models.Assistant.synchronize_assistant_mcp_server_tools(
            request.state["db"], asst.id, []
        )
        await models.Thread.update_mcp_server_tools_available(
            request.state["db"],
            asst.id,
            [],
            asst.version,
            asst.interaction_mode,
        )

    if "temperature" in req.model_fields_set:
        openai_update["temperature"] = req.temperature
        asst.temperature = req.temperature

    if (
        "should_record_user_information" in req.model_fields_set
        and req.should_record_user_information is not None
    ):
        asst.should_record_user_information = req.should_record_user_information

    if (
        "allow_user_file_uploads" in req.model_fields_set
        and req.allow_user_file_uploads is not None
    ):
        asst.allow_user_file_uploads = req.allow_user_file_uploads

    if (
        "allow_user_image_uploads" in req.model_fields_set
        and req.allow_user_image_uploads is not None
    ):
        asst.allow_user_image_uploads = req.allow_user_image_uploads

    if (
        "hide_reasoning_summaries" in req.model_fields_set
        and req.hide_reasoning_summaries is not None
    ):
        asst.hide_reasoning_summaries = req.hide_reasoning_summaries

    if (
        "hide_file_search_result_quotes" in req.model_fields_set
        and req.hide_file_search_result_quotes is not None
    ):
        asst.hide_file_search_result_quotes = req.hide_file_search_result_quotes

    if (
        "hide_file_search_document_names" in req.model_fields_set
        and req.hide_file_search_document_names is not None
    ):
        # Validate before assignment
        # Determine what the value of hide_file_search_result_quotes will be after this request
        new_hide_file_search_result_quotes = (
            req.hide_file_search_result_quotes
            if "hide_file_search_result_quotes" in req.model_fields_set
            and req.hide_file_search_result_quotes is not None
            else asst.hide_file_search_result_quotes
        )
        if (
            req.hide_file_search_document_names
            and not new_hide_file_search_result_quotes
        ):
            raise HTTPException(
                status_code=400,
                detail="Cannot hide document names while showing result quotes. Please enable 'Hide File Search Result Quotes from Members' or disable 'Completely Hide File Search Results from Members'.",
            )
        asst.hide_file_search_document_names = req.hide_file_search_document_names

    if (
        "hide_file_search_queries" in req.model_fields_set
        and req.hide_file_search_queries is not None
    ):
        asst.hide_file_search_queries = req.hide_file_search_queries

    if (
        "hide_mcp_server_call_details" in req.model_fields_set
        and req.hide_mcp_server_call_details is not None
    ):
        asst.hide_mcp_server_call_details = req.hide_mcp_server_call_details

    if (
        "hide_web_search_sources" in req.model_fields_set
        and req.hide_web_search_sources is not None
    ):
        asst.hide_web_search_sources = req.hide_web_search_sources

    if (
        "hide_web_search_actions" in req.model_fields_set
        and req.hide_web_search_actions is not None
    ):
        # Validate before assignment
        # Determine what the value of hide_web_search_sources will be after this request
        new_hide_web_search_sources = (
            req.hide_web_search_sources
            if "hide_web_search_sources" in req.model_fields_set
            and req.hide_web_search_sources is not None
            else asst.hide_web_search_sources
        )
        if req.hide_web_search_actions and not new_hide_web_search_sources:
            raise HTTPException(
                status_code=400,
                detail="Cannot hide web search actions while showing sources. Please enable 'Hide Web Search Sources from Members' or disable 'Completely Hide Web Search Actions from Members'.",
            )
        asst.hide_web_search_actions = req.hide_web_search_actions

    if is_toggling_publish_status:
        ptuple = (f"class:{class_id}#member", "can_view", f"assistant:{asst.id}")
        if req.published:
            asst.published = func.now()
            grants.append(ptuple)
        else:
            asst.published = None
            revokes.append(ptuple)

    if "name" in req.model_fields_set and req.name is not None:
        asst.name = req.name

    await models.Thread.update_tools_available(
        request.state["db"], asst.id, asst.tools, asst.version, asst.interaction_mode
    )
    request.state["db"].add(asst)
    await request.state["db"].flush()
    await request.state["db"].refresh(asst)

    if not asst.instructions:
        raise HTTPException(400, "Instructions cannot be empty.")
    if update_instructions:
        openai_update["instructions"] = format_instructions(
            asst.instructions,
            use_latex=asst.use_latex,
            use_image_descriptions=asst.use_image_descriptions,
        )

    if openai_update:
        if asst.version == 3:
            responses_api_transition_logger.debug(
                "Updating a Version 3 assistant; skipping update of OpenAI Assistants API object."
            )
            # Delete vector store as late as possible to avoid orphaned assistant
            if vector_store_id_to_delete:
                await delete_vector_store_oai(openai_client, vector_store_id_to_delete)
        else:
            try:
                if not asst.assistant_id:
                    new_tool_resources = {}

                    if (
                        asst.code_interpreter_files
                        and asst.code_interpreter_files != []
                    ):
                        new_tool_resources["code_interpreter"] = {
                            "file_ids": [f.file_id for f in asst.code_interpreter_files]
                        }
                    if asst.vector_store_id:
                        new_tool_resources["file_search"] = {
                            "vector_store_ids": [asst.vector_store.id]
                        }
                    new_asst = await openai_client.beta.assistants.create(
                        instructions=format_instructions(
                            asst.instructions,
                            use_latex=asst.use_latex,
                            use_image_descriptions=asst.use_image_descriptions,
                        ),
                        model=_model,
                        tools=json.loads(asst.tools),
                        temperature=asst.temperature,
                        metadata={
                            "class_id": class_id,
                            "creator_id": str(request.state["session"].user.id),
                        },
                        tool_resources=new_tool_resources,
                        extra_body=new_reasoning_effort_body,
                    )
                    asst.assistant_id = new_asst.id
                    request.state["db"].add(asst)
                    await request.state["db"].flush()
                    await request.state["db"].refresh(asst)
                else:
                    await openai_client.beta.assistants.update(
                        assistant_id=asst.assistant_id, **openai_update
                    )
                # Delete vector store as late as possible to avoid orphaned assistant
                if vector_store_id_to_delete:
                    await delete_vector_store_oai(
                        openai_client, vector_store_id_to_delete
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

    if (
        "deleted_private_files" in req.model_fields_set
        and req.deleted_private_files != []
    ):
        try:
            files_to_delete = await models.File.get_files_not_used_by_assistant(
                request.state["db"],
                asst.id,
                req.deleted_private_files,
            )
            # Delete any private files that were removed
            await handle_delete_files(
                request.state["db"],
                request.state["authz"],
                openai_client,
                files_to_delete,
                class_id=int(class_id),
            )
        except Exception as e:
            logger.exception(
                "Error deleting private files while updating assistant: %s", e
            )

    await request.state["authz"].write_safe(grant=grants, revoke=revokes)
    return asst


def mcp_server_to_response(
    server: models.MCPServerTool,
) -> schemas.MCPServerToolResponse:
    """Convert an MCPServerTool to MCPServerToolResponse with inferred auth_type"""
    # Infer auth_type from stored data
    if server.authorization_token:
        auth_type = schemas.MCPAuthType.TOKEN
    elif server.headers:
        auth_type = schemas.MCPAuthType.HEADER
    else:
        auth_type = schemas.MCPAuthType.NONE

    # Parse headers JSON if present
    headers_dict = None
    if server.headers and auth_type == schemas.MCPAuthType.HEADER:
        headers_dict = json.loads(server.headers)

    return schemas.MCPServerToolResponse(
        display_name=server.display_name,
        server_label=server.server_label,
        server_url=server.server_url,
        auth_type=auth_type,
        headers=headers_dict,
        description=server.description,
        enabled=server.enabled,
    )


@v1.get(
    "/class/{class_id}/assistant/{assistant_id}/mcp_servers",
    dependencies=[Depends(Authz("can_edit", "assistant:{assistant_id}"))],
    response_model=schemas.MCPServerToolsResponse,
)
async def get_assistant_mcp_servers(
    class_id: str, assistant_id: str, request: StateRequest
):
    """Get MCP servers configured for an assistant"""
    asst = await models.Assistant.get_by_id(request.state["db"], int(assistant_id))
    if not asst:
        raise HTTPException(404, "Assistant not found.")

    mcp_servers = await models.MCPServerTool.get_for_assistant(
        request.state["db"], asst.id
    )

    return {"mcp_servers": [mcp_server_to_response(server) for server in mcp_servers]}


@v1.post(
    "/class/{class_id}/assistant/{assistant_id}/publish",
    dependencies=[Depends(Authz("can_publish", "assistant:{assistant_id}"))],
    response_model=schemas.GenericStatus,
)
async def publish_assistant(class_id: str, assistant_id: str, request: StateRequest):
    asst = await models.Assistant.get_by_id(request.state["db"], int(assistant_id))
    asst.published = func.now()
    request.state["db"].add(asst)
    await request.state["authz"].write_safe(
        grant=[(f"class:{class_id}#member", "can_view", f"assistant:{assistant_id}")]
    )
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}/publish",
    dependencies=[Depends(Authz("can_publish", "assistant:{assistant_id}"))],
    response_model=schemas.GenericStatus,
)
async def unpublish_assistant(class_id: str, assistant_id: str, request: StateRequest):
    asst = await models.Assistant.get_by_id(request.state["db"], int(assistant_id))
    asst.published = None
    request.state["db"].add(asst)
    await request.state["authz"].write_safe(
        revoke=[(f"class:{class_id}#member", "can_view", f"assistant:{assistant_id}")]
    )
    return {"status": "ok"}


@v1.post(
    "/class/{class_id}/assistant/{assistant_id}/lock",
    dependencies=[Depends(Authz("admin", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def lock_assistant(class_id: str, assistant_id: str, request: StateRequest):
    asst = await models.Assistant.get_by_id(request.state["db"], int(assistant_id))
    if not asst:
        raise HTTPException(404, "Assistant not found.")
    asst.locked = True
    request.state["db"].add(asst)
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}/lock",
    dependencies=[Depends(Authz("admin", "class:{class_id}"))],
    response_model=schemas.GenericStatus,
)
async def unlock_assistant(class_id: str, assistant_id: str, request: StateRequest):
    asst = await models.Assistant.get_by_id(request.state["db"], int(assistant_id))
    if not asst:
        raise HTTPException(404, "Assistant not found.")
    asst.locked = False
    request.state["db"].add(asst)
    return {"status": "ok"}


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[Depends(Authz("can_delete", "assistant:{assistant_id}"))],
    response_model=schemas.GenericStatus,
)
async def delete_assistant(
    class_id: str,
    assistant_id: str,
    request: StateRequest,
    openai_client: OpenAIClient,
):
    asst = await models.Assistant.get_by_id(request.state["db"], int(assistant_id))

    # Detach the vector store from the assistant and delete it
    vector_store_obj_id = None
    if asst.vector_store_id:
        vector_store_id = asst.vector_store_id
        asst.vector_store_id = None
        # Keep the OAI vector store ID for deletion
        vector_store_obj_id = await delete_vector_store_db(
            request.state["db"], vector_store_id
        )

    # Remove any CI files associations with the assistant
    stmt = delete(models.code_interpreter_file_assistant_association).where(
        models.code_interpreter_file_assistant_association.c.assistant_id
        == int(asst.id)
    )
    await request.state["db"].execute(stmt)

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
    await request.state["db"].execute(_stmt)

    # Keep the OAI assistant ID for deletion
    assistant_id = asst.assistant_id
    await models.Assistant.delete(request.state["db"], asst.id)

    # Delete vector store as late as possible to avoid orphaned assistant
    if vector_store_obj_id:
        await delete_vector_store_oai(openai_client, vector_store_obj_id)

    if assistant_id:
        try:
            await openai_client.beta.assistants.delete(assistant_id)
        except openai.NotFoundError:
            pass
        except openai.BadRequestError as e:
            raise HTTPException(
                400, get_details_from_api_error(e, "OpenAI rejected this request")
            )

    # clean up grants
    await request.state["authz"].write_safe(revoke=revokes)
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/assistant/{assistant_id}/files",
    dependencies=[Depends(Authz("can_view", "assistant:{assistant_id}"))],
    response_model=schemas.AssistantFilesResponse,
)
async def get_assistant_files(
    class_id: str,
    assistant_id: str,
    request: StateRequest,
):
    asst = await models.Assistant.get_by_id_with_ci_files(
        request.state["db"], int(assistant_id)
    )
    file_search_files = []
    if asst.vector_store_id:
        file_search_files = await models.VectorStore.get_files_by_id(
            request.state["db"], asst.vector_store_id
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
async def get_image(file_id: str, request: StateRequest, openai_client: OpenAIClient):
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
    request: StateRequest,
    openai_client: OpenAIClient,
):
    thread = await models.Thread.get_by_id(request.state["db"], int(thread_id))

    if not thread:
        raise HTTPException(
            status_code=404,
            detail="Thread not found",
        )

    if thread.version <= 2:
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
    elif thread.version == 3:
        file = await models.File.get_by_id_with_download(
            request.state["db"], int(file_id)
        )
        if not file or not file.s3_file:
            raise HTTPException(
                status_code=404,
                detail="File not found",
            )

        return StreamingResponse(
            config.file_store.store.get(name=file.s3_file.key),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={file.name}"},
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported thread version",
        )


@v1.get(
    "/me",
)
async def get_me(request: StateRequest):
    """Get the session information."""
    return request.state["session"]


@v1.put(
    "/me",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.User,
)
async def update_me(request: StateRequest, update: schemas.UpdateUserInfo):
    """Update the user profile."""
    return await models.User.update_info(
        request.state["db"], request.state["session"].user.id, update
    )


@v1.get(
    "/me/external-logins",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.ExternalLoginsResponse,
)
async def get_external_logins(request: StateRequest):
    """Get the user's external logins."""
    return {
        "external_logins": await models.User.get_external_logins_by_id(
            request.state["db"], request.state["session"].user.id
        )
    }


@v1.get(
    "/me/activity_summaries",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.ActivitySummarySubscriptions,
)
async def get_activity_summaries(request: StateRequest):
    """Get the user's activity summaries."""

    # Get all groups the user is a moderator of
    moderator_class_ids = await request.state["authz"].list(
        f"user:{request.state['session'].user.id}",
        "teacher",
        "class",
    )

    return await models.UserClassRole.get_activity_summary_subscriptions(
        request.state["db"], request.state["session"].user.id, moderator_class_ids
    )


@v1.post(
    "/me/activity_summaries",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def subscribe_to_all_summaries(
    request: StateRequest,
):
    """Subscribe to all activity summaries."""
    moderator_classes = await request.state["authz"].list(
        f"user:{request.state['session'].user.id}",
        "teacher",
        "class",
    )

    if not moderator_classes:
        raise HTTPException(
            403,
            "You must be a Moderator in at least one class to subscribe to activity summaries.",
        )

    await models.UserClassRole.subscribe_to_all_summaries(
        request.state["db"], request.state["session"].user.id
    )
    return {"status": "ok"}


@v1.delete(
    "/me/activity_summaries",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def unsubscribe_from_all_summaries(
    request: StateRequest,
):
    """Unsubscribe from all activity summaries."""
    moderator_classes = await request.state["authz"].list(
        f"user:{request.state['session'].user.id}",
        "teacher",
        "class",
    )

    if not moderator_classes:
        raise HTTPException(
            403,
            "You must be a Moderator in at least one class to subscribe to activity summaries.",
        )

    await models.UserClassRole.unsubscribe_from_all_summaries(
        request.state["db"], request.state["session"].user.id
    )
    return {"status": "ok"}


@v1.post(
    "/me/activity_summaries/create",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def enable_dna_as_create(
    request: StateRequest,
):
    """Enable DNA as create."""
    await models.User.update_dna_as_create(
        request.state["db"], request.state["session"].user.id, True
    )
    return {"status": "ok"}


@v1.delete(
    "/me/activity_summaries/create",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def disable_dna_as_create(
    request: StateRequest,
):
    """Disable DNA as create."""
    await models.User.update_dna_as_create(
        request.state["db"], request.state["session"].user.id, False
    )
    return {"status": "ok"}


@v1.post(
    "/me/activity_summaries/join",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def enable_dna_as_join(
    request: StateRequest,
):
    """Enable DNA as join."""
    await models.User.update_dna_as_join(
        request.state["db"], request.state["session"].user.id, True
    )
    return {"status": "ok"}


@v1.delete(
    "/me/activity_summaries/join",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def disable_dna_as_join(
    request: StateRequest,
):
    """Disable DNA as join."""
    await models.User.update_dna_as_join(
        request.state["db"], request.state["session"].user.id, False
    )
    return {"status": "ok"}


@v1.get(
    "/me/grants/list",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GrantsList,
)
async def get_grants_list(rel: str, obj: str, request: StateRequest):
    """List objects for which user has a specific relation."""
    sub = f"user:{request.state['session'].user.id}"
    results = await request.state["authz"].list(
        sub,
        rel,
        obj,
    )
    return {
        "subject_type": "user",
        "subject_id": request.state["session"].user.id,
        "relation": rel,
        "target_type": obj,
        "target_ids": results,
    }


@v1.post(
    "/me/grants",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Grants,
)
async def get_grants(query: schemas.GrantsQuery, request: StateRequest):
    checks = list[Relation]()
    user_names = list[str]()

    if request.state["is_anonymous"]:
        if request.state["anonymous_share_token_auth"] is not None:
            user_names.append(
                request.state["anonymous_share_token_auth"],
            )
        if request.state["anonymous_session_token_auth"] is not None:
            user_names.append(
                request.state["anonymous_session_token_auth"],
            )
    else:
        user_names.append(request.state["auth_user"])

    check_both_anonymous_tokens = len(user_names) == 2
    for grant in query.grants:
        target = f"{grant.target_type}:{grant.target_id}"
        checks.extend(
            [
                (
                    user_name,
                    grant.relation,
                    target,
                )
                for user_name in user_names
            ]
        )

    results = await request.state["authz"].check(checks)
    return {
        "grants": [
            schemas.GrantDetail(
                request=query.grants[i],
                verdict=any(results[i * 2 : i * 2 + 2])
                if check_both_anonymous_tokens
                else results[i],
            )
            for i in range(len(query.grants))
        ],
    }


@v1.get(
    "/me/terms/{policy_id}",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.AgreementBody,
)
async def get_user_agreement(
    policy_id: str,
    request: StateRequest,
):
    """Get the user agreement."""
    agreement = await models.Agreement.get_by_policy_id(
        request.state["db"], int(policy_id)
    )
    if not agreement:
        raise HTTPException(404, "Agreement not found.")
    return agreement


@v1.post(
    "/me/terms/{policy_id}",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def accept_user_agreement(policy_id: str, request: StateRequest):
    """Accept the user agreement."""
    policy = await models.AgreementPolicy.get_by_id_if_eligible(
        request.state["db"], int(policy_id), request.state["session"].user.id
    )
    if not policy:
        raise HTTPException(404, "Agreement not found.")

    await models.AgreementAcceptance.accept_agreement(
        request.state["db"],
        request.state["session"].user.id,
        policy.agreement_id,
        policy.id,
    )

    return {"status": "ok"}


@v1.get(
    "/admin/terms/agreement",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.Agreements,
)
async def list_user_agreements(request: StateRequest):
    """Get all user agreements."""
    agreements = await models.Agreement.get_all(request.state["db"])
    return {"agreements": agreements}


@v1.post(
    "/admin/terms/agreement",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def create_user_agreement(
    req: schemas.CreateAgreementRequest,
    request: StateRequest,
):
    """Create a user agreement."""
    await models.Agreement.create(request.state["db"], req)
    return {"status": "ok"}


@v1.get(
    "/admin/terms/agreement/{agreement_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.AgreementDetail,
)
async def get_user_agreement_detail(
    agreement_id: str,
    request: StateRequest,
):
    """Get a user agreement."""
    agreement = await models.Agreement.get_by_id_with_policies(
        request.state["db"], int(agreement_id)
    )
    if not agreement:
        raise HTTPException(404, "Agreement not found.")
    return agreement


@v1.put(
    "/admin/terms/agreement/{agreement_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def update_user_agreement(
    agreement_id: str,
    req: schemas.UpdateAgreementRequest,
    request: StateRequest,
):
    """Update a user agreement."""
    agreement = await models.Agreement.get_by_id_with_policies(
        request.state["db"], int(agreement_id)
    )

    if not agreement:
        raise HTTPException(404, "Agreement not found.")

    # If the agreement is already attached to a policy, updates are not allowed
    if agreement.policies:
        raise HTTPException(
            400, "Cannot update an agreement that is already attached to a policy."
        )

    if "name" in req.model_fields_set and req.name is not None:
        agreement.name = req.name

    if "body" in req.model_fields_set and req.body is not None:
        agreement.body = req.body

    request.state["db"].add(agreement)
    await request.state["db"].flush()
    return {"status": "ok"}


@v1.get(
    "/admin/terms/policy",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.AgreementPolicies,
)
async def list_user_agreement_policies(request: StateRequest):
    """Get all user agreement policies."""
    policies = await models.AgreementPolicy.get_all(request.state["db"])
    return {"policies": policies}


@v1.post(
    "/admin/terms/policy",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def create_user_agreement_policy(
    req: schemas.CreateAgreementPolicyRequest,
    request: StateRequest,
):
    """Create a user agreement policy."""
    if req.apply_to_all and req.limit_to_providers:
        raise HTTPException(
            400,
            "Cannot limit user agreement to specific users when Display to All is selected.",
        )
    if not req.apply_to_all and not req.limit_to_providers:
        raise HTTPException(
            400,
            "The user agreement must be limited to specific users or apply to all users.",
        )

    agreement = await models.Agreement.get_by_id(
        request.state["db"], int(req.agreement_id)
    )
    if not agreement:
        raise HTTPException(404, "Agreement not found.")

    providers = []
    if req.limit_to_providers:
        providers = await models.ExternalLoginProvider.get_by_ids(
            request.state["db"], req.limit_to_providers
        )

    policy = models.AgreementPolicy(
        agreement_id=agreement.id,
        name=req.name,
        apply_to_all=req.apply_to_all,
        limit_to_providers=providers,
    )
    request.state["db"].add(policy)
    await request.state["db"].flush()

    return {"status": "ok"}


@v1.get(
    "/admin/terms/policy/{policy_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.AgreementPolicyDetail,
)
async def get_user_agreement_policy(
    policy_id: str,
    request: StateRequest,
):
    """Get a user agreement policy."""
    policy = await models.AgreementPolicy.get_by_id_with_external_logins(
        request.state["db"], int(policy_id)
    )
    if not policy:
        raise HTTPException(404, "Policy not found.")
    return policy


@v1.put(
    "/admin/terms/policy/{policy_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def update_user_agreement_policy(
    policy_id: str,
    req: schemas.UpdateAgreementPolicyRequest,
    request: StateRequest,
):
    """Update a user agreement policy."""
    policy = await models.AgreementPolicy.get_by_id_with_external_logins(
        request.state["db"], int(policy_id)
    )
    if not policy:
        raise HTTPException(404, "Policy not found.")

    if "name" in req.model_fields_set and req.name is not None:
        policy.name = req.name

    if "agreement_id" in req.model_fields_set and req.agreement_id is not None:
        if policy.not_before:
            raise HTTPException(
                400,
                "Cannot change the agreement of a policy that has already been enabled.",
            )
        agreement = await models.Agreement.get_by_id(
            request.state["db"], int(req.agreement_id)
        )
        if not agreement:
            raise HTTPException(404, "Agreement not found.")
        policy.agreement_id = agreement.id

    if "apply_to_all" in req.model_fields_set and req.apply_to_all is not None:
        if req.apply_to_all and req.limit_to_providers:
            raise HTTPException(
                400,
                "Cannot limit user agreement to specific users when Display to All is selected.",
            )
        if not req.apply_to_all and not req.limit_to_providers:
            raise HTTPException(
                400,
                "The user agreement must be limited to specific users or apply to all users.",
            )
        policy.apply_to_all = req.apply_to_all

    if "limit_to_providers" in req.model_fields_set:
        if (
            policy.apply_to_all
            and req.limit_to_providers is not None
            and req.limit_to_providers != []
        ):
            raise HTTPException(
                400,
                "Cannot limit user agreement to specific users when Display to All is selected.",
            )
        if not policy.apply_to_all and (
            req.limit_to_providers is None or req.limit_to_providers == []
        ):
            raise HTTPException(
                400,
                "The user agreement must be limited to specific users or apply to all users.",
            )
        providers = []
        if req.limit_to_providers:
            providers = await models.ExternalLoginProvider.get_by_ids(
                request.state["db"], req.limit_to_providers
            )
        policy.limit_to_providers = providers

    request.state["db"].add(policy)
    await request.state["db"].flush()

    return {"status": "ok"}


@v1.patch(
    "/admin/terms/policy/{policy_id}/status",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def toggle_user_agreement_policy(
    policy_id: str,
    req: schemas.ToggleAgreementPolicyRequest,
    request: StateRequest,
):
    """Enable a user agreement policy."""
    policy = await models.AgreementPolicy.get_by_id(request.state["db"], int(policy_id))
    if not policy:
        raise HTTPException(404, "Policy not found.")

    match req.action:
        case "enable":
            if policy.not_before:
                raise HTTPException(
                    400, "Cannot enable a policy that has already been enabled."
                )
            policy.not_before = func.now()
        case "disable":
            if not policy.not_before:
                raise HTTPException(
                    400, "Cannot disable a policy that has not been enabled."
                )
            if policy.not_after:
                raise HTTPException(
                    400, "Cannot disable a policy that has already been disabled."
                )
            policy.not_after = func.now()
        case _:
            raise HTTPException(400, "Invalid action.")

    request.state["db"].add(policy)
    await request.state["db"].flush()
    return {"status": "ok"}


@v1.get(
    "/admin/providers",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.ExternalLoginProviders,
)
async def get_external_login_providers(request: StateRequest):
    """Get the external login providers."""
    providers = await models.ExternalLoginProvider.get_all(request.state["db"])
    return {"providers": providers}


@v1.put(
    "/admin/providers/{provider_id}",
    dependencies=[Depends(Authz("admin"))],
    response_model=schemas.GenericStatus,
)
async def update_external_login_provider(
    provider_id: str,
    req: schemas.UpdateExternalLoginProvider,
    request: StateRequest,
):
    """Update an external login provider."""
    provider = await models.ExternalLoginProvider.get_by_id(
        request.state["db"], int(provider_id)
    )
    if not provider:
        raise HTTPException(404, "Provider not found.")
    provider.description = req.description
    provider.display_name = req.display_name
    request.state["db"].add(provider)
    await request.state["db"].flush()
    return {"status": "ok"}


@v1.get(
    "/support",
    response_model=schemas.Support,
)
async def get_support(request: StateRequest):
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
    request: StateRequest,
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


@asynccontextmanager
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


app = FastAPI(
    lifespan=lifespan,
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=None,
)


@app.exception_handler(Exception)
async def handle_exception(request: StateRequest, exc: Exception):
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

try:
    if config.lti:
        from pingpong.lti.server import lti_router

        v1.include_router(lti_router, prefix="/lti")
        logger.info("Mounted Canvas Connect routes")
except Exception:
    # If LTI is not configured or import fails, skip mounting
    logger.exception("Failed to mount Canvas Connect routes.")


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}
