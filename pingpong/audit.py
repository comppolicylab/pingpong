import json
import logging
from contextvars import ContextVar
from typing import Any

from starlette.requests import HTTPConnection

access_logger = logging.getLogger("pingpong.access")
audit_logger = logging.getLogger("pingpong.audit")
logger = logging.getLogger(__name__)

_current: ContextVar[HTTPConnection | None] = ContextVar("audit_request", default=None)

ROUTE_EVENTS = {
    # Authentication
    "login_magic": "auth.magic_link.request",
    "auth": "auth.magic_link.use",
    "login_sso": "auth.sso.start",
    "login_sso_saml_acs": "auth.sso.saml",
    "login_sso_exchange": "auth.sso.exchange",
    "auth_canvas": "auth.canvas",
    "lti_launch": "auth.lti.launch",
    # Users and permissions
    "add_email_to_user": "user.email.add",
    "delete_email_from_user": "user.email.remove",
    "merge_users": "user.merge",
    "update_me": "user.update",
    "manage_authz": "authz.manage",
    "inspect_authz": "authz.inspect",
    "list_all_user_permissions": "authz.inspect_all",
    "add_users_to_class": "class.users.add",
    "update_user_class_role": "class.users.role",
    "remove_user_from_class": "class.users.remove",
    "add_institution_admin": "institution.admin.add",
    "remove_institution_admin": "institution.admin.remove",
    "add_lecture_lesson_access": "admin.lecture_lessons.access.add",
    "remove_lecture_lesson_access": "admin.lecture_lessons.access.remove",
    # Institutions and groups
    "create_institution": "institution.create",
    "update_institution": "institution.update",
    "copy_institution": "institution.copy",
    "set_institution_default_api_key": "institution.api_key.update",
    "create_class": "class.create",
    "update_class": "class.update",
    "transfer_class": "class.transfer",
    "copy_class": "class.copy",
    "delete_class": "class.delete",
    "export_class_threads": "class.export",
    "export_class_threads_multiple_classes": "admin.export",
    # Keys and credentials
    "update_class_api_key": "class.api_key.update",
    "create_class_credential": "class.credential.create",
    "remove_canvas_connection": "class.canvas.disconnect",
    "update_external_login_provider": "admin.login_provider.update",
    "create_connector_config": "admin.connector.create",
    "update_connector_config": "admin.connector.update",
    # LTI
    "create_manual_lti_registration": "admin.lti.registration.create",
    "update_lti_registration": "admin.lti.registration.update",
    "set_lti_registration_status": "admin.lti.registration.status",
    "accept_manual_lti_registration": "admin.lti.registration.accept",
    "set_lti_registration_enabled": "admin.lti.registration.enabled",
    "set_lti_registration_institutions": "admin.lti.registration.institutions",
    "register_lti_instance": "lti.register",
    "create_lti_group": "lti.group.create",
    "link_lti_group": "lti.group.link",
    # Assistants and share links
    "create_assistant": "assistant.create",
    "update_assistant": "assistant.update",
    "copy_assistant": "assistant.copy",
    "delete_assistant": "assistant.delete",
    "publish_assistant": "assistant.publish",
    "unpublish_assistant": "assistant.unpublish",
    "lock_assistant": "assistant.lock",
    "unlock_assistant": "assistant.unlock",
    "share_assistant": "share_link.create",
    "update_assistant_share_name": "share_link.update",
    "unshare_assistant": "share_link.revoke",
    # Threads
    "delete_thread": "thread.delete",
    "publish_thread": "thread.publish",
    "unpublish_thread": "thread.unpublish",
    # Administration
    "create_user_agreement": "admin.terms.agreement.create",
    "update_user_agreement": "admin.terms.agreement.update",
    "create_user_agreement_policy": "admin.terms.policy.create",
    "update_user_agreement_policy": "admin.terms.policy.update",
    "toggle_user_agreement_policy": "admin.terms.policy.status",
    "reset_model_cache": "admin.model_cache.reset",
    "migrate_models": "admin.models.migrate",
    # Open Access
    "launch": "oa.launch",
    "renew": "oa.renew",
    "exchange": "oa.exchange",
    "catalogue": "oa.catalogue",
}


def client_ip(connection: HTTPConnection) -> str | None:
    forwarded = connection.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.rsplit(",", 1)[-1].strip() or None
    return connection.client.host if connection.client else None


def actor(connection: HTTPConnection | None) -> dict[str, Any]:
    if connection is None:
        return {}
    state = connection.scope.get("state") or {}
    session = state.get("session")
    open_access = state.get("open_access")
    return {
        "ip": client_ip(connection),
        "user_id": session.user.id if session is not None and session.user else None,
        "principal_id": open_access.claims.pid if open_access is not None else None,
        "anonymous_session_id": state.get("anonymous_session_id"),
    }


def bind_request(connection: HTTPConnection):
    return _current.set(connection)


def unbind_request(token) -> None:
    _current.reset(token)


def _write(logger: logging.Logger, record: dict[str, Any]) -> None:
    logger.info(json.dumps(record, default=str, separators=(",", ":")))


def audit(event: str, **fields: Any) -> None:
    connection = _current.get()
    route = connection.scope.get("route") if connection is not None else None
    _write(
        audit_logger,
        {
            "audit": event,
            **actor(connection),
            "route": getattr(route, "path", None),
            **fields,
        },
    )


def access(connection: HTTPConnection, method: str, status: int, ms: int) -> None:
    route = connection.scope.get("route")
    _write(
        access_logger,
        {
            **actor(connection),
            "method": method,
            "route": getattr(route, "path", None),
            "path": connection.url.path,
            "status": status,
            "ms": ms,
        },
    )


def route_event(connection: HTTPConnection, status: int) -> None:
    route = connection.scope.get("route")
    event = ROUTE_EVENTS.get(getattr(route, "name", ""))
    if event is None and connection.url.path.startswith("/api/v1/admin/"):
        event = "admin.access"
    if event is not None:
        audit(
            event,
            outcome="success" if status < 400 else "failure",
            status=status,
            target=connection.scope.get("path_params") or {},
        )


async def check_elevated_access(connection: HTTPConnection) -> None:
    try:
        await _check_elevated_access(connection)
    except Exception:
        logger.exception("Failed to check elevated access")


async def _check_elevated_access(connection: HTTPConnection) -> None:
    state = connection.scope.get("state") or {}
    session = state.get("session")
    authz = state.get("authz")
    params = connection.path_params
    if session is None or session.user is None or authz is None:
        return
    elevated = state["elevated_access"] = []
    user = f"user:{session.user.id}"
    if "institution_id" in params:
        institution = f"institution:{params['institution_id']}"
        if not any(
            [
                await authz.read_tuples(relation, institution, user)
                for relation in ("admin", "can_create_class")
            ]
        ):
            elevated.append(institution)
    if "class_id" not in params:
        return
    class_ = f"class:{params['class_id']}"
    thread = f"thread:{params['thread_id']}" if "thread_id" in params else None
    checks = [(user, "teacher", class_), (user, "student", class_)]
    if thread is not None:
        checks += [(user, "party", thread), (user, "can_view", thread)]
    teacher, student, *thread_checks = await authz.check(checks)
    if thread is None:
        direct = teacher or student
    else:
        party, can_view = thread_checks
        direct = party or teacher or (student and can_view)
    if not direct:
        elevated.append(thread or class_)


def record_elevated_access(connection: HTTPConnection, status: int) -> None:
    state = connection.scope.get("state") or {}
    if status >= 400:
        return
    for scope in state.get("elevated_access", ()):
        audit(
            "privilege.elevated",
            scope=scope,
            target=connection.scope.get("path_params") or {},
        )
