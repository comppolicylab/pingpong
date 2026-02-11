"""Shared LTI role helpers."""

from pingpong.schemas import ClassUserRoles

from .constants import LTI_ADMIN_ROLES, LTI_INSTRUCTOR_ROLES, LTI_STUDENT_ROLES


def _role_values(roles: object) -> set[str]:
    if not isinstance(roles, list):
        return set()
    return {role for role in roles if isinstance(role, str)}


def is_admin(roles: object) -> bool:
    values = _role_values(roles)
    return any(role in LTI_ADMIN_ROLES for role in values)


def is_instructor(roles: object) -> bool:
    values = _role_values(roles)
    return any(role in LTI_INSTRUCTOR_ROLES for role in values)


def is_student(roles: object) -> bool:
    values = _role_values(roles)
    return any(role in LTI_STUDENT_ROLES for role in values)


def class_user_roles_from_lti_roles(roles: object) -> ClassUserRoles | None:
    if is_admin(roles):
        return ClassUserRoles(admin=True, teacher=False, student=False)
    if is_instructor(roles):
        return ClassUserRoles(admin=False, teacher=True, student=False)
    if is_student(roles):
        return ClassUserRoles(admin=False, teacher=False, student=True)
    return None
