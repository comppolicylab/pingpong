"""Shared constants for LTI launch and Canvas Connect NRPS sync."""

SSO_FIELD_FULL_NAME: dict[str, str] = {
    "canvas.sisIntegrationId": "Canvas.user.sisIntegrationId",
    "canvas.sisSourceId": "Canvas.user.sisSourceId",
    "person.sourcedId": "Person.sourcedId",
}

ISSUER_KEY = "issuer"
AUTHORIZATION_ENDPOINT_KEY = "authorization_endpoint"
REGISTRATION_ENDPOINT_KEY = "registration_endpoint"
KEYS_ENDPOINT_KEY = "jwks_uri"
TOKEN_ENDPOINT_KEY = "token_endpoint"
SCOPES_SUPPORTED_KEY = "scopes_supported"
TOKEN_ALG_KEY = "id_token_signing_alg_values_supported"
SUBJECT_TYPES_KEY = "subject_types_supported"
LTI_REGISTRATION_URL_FIELDS = (
    "auth_login_url",
    "auth_token_url",
    "key_set_url",
)
LTI_OPENID_CONFIGURATION_URL_KEYS = (
    AUTHORIZATION_ENDPOINT_KEY,
    REGISTRATION_ENDPOINT_KEY,
    KEYS_ENDPOINT_KEY,
    TOKEN_ENDPOINT_KEY,
)

PLATFORM_CONFIGURATION_KEY = (
    "https://purl.imsglobal.org/spec/lti-platform-configuration"
)
MESSAGE_TYPES_KEY = "messages_supported"
MESSAGE_TYPE = "LtiResourceLinkRequest"
CANVAS_MESSAGE_PLACEMENT = "https://canvas.instructure.com/lti/course_navigation"
LTI_TOOL_CONFIGURATION_KEY = "https://purl.imsglobal.org/spec/lti-tool-configuration"

CANVAS_ACCOUNT_NAME_KEY = "https://canvas.instructure.com/lti/account_name"
CANVAS_ACCOUNT_LTI_GUID_KEY = "https://canvas.instructure.com/lti/account_lti_guid"

LTI_DEPLOYMENT_ID_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/deployment_id"
LTI_CLAIM_CUSTOM_KEY = "https://purl.imsglobal.org/spec/lti/claim/custom"
LTI_CLAIM_CONTEXT_KEY = "https://purl.imsglobal.org/spec/lti/claim/context"
LTI_CLAIM_ROLES_KEY = "https://purl.imsglobal.org/spec/lti/claim/roles"
LTI_CLAIM_RESOURCE_LINK_KEY = "https://purl.imsglobal.org/spec/lti/claim/resource_link"
LTI_CLAIM_TOOL_PLATFORM_KEY = "https://purl.imsglobal.org/spec/lti/claim/tool_platform"
LTI_CLAIM_NRPS_KEY = "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice"

LTI_CUSTOM_SSO_PROVIDER_ID_KEY = "sso_provider_id"
LTI_CUSTOM_SSO_VALUE_KEY = "sso_value"

LTI_CUSTOM_PARAM_DEFAULT_VALUES = {
    LTI_CUSTOM_SSO_PROVIDER_ID_KEY: ["0"],
    LTI_CUSTOM_SSO_VALUE_KEY: [""]
    + [f"${field}" for field in SSO_FIELD_FULL_NAME.values()],
    "canvas_course_id": ["$Canvas.course.id"],
    "canvas_term_name": ["$Canvas.term.name"],
}

NRPS_CONTEXT_MEMBERSHIP_SCOPE = (
    "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"
)
REQUIRED_SCOPES = [NRPS_CONTEXT_MEMBERSHIP_SCOPE]

TOKEN_REQUEST_CONTENT_TYPE = "application/x-www-form-urlencoded"
CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
CLIENT_CREDENTIALS_GRANT_TYPE = "client_credentials"
NRPS_MEMBERSHIP_CONTAINER_CONTENT_TYPE = (
    "application/vnd.ims.lti-nrps.v2.membershipcontainer+json"
)
NRPS_NEXT_PAGE_KEY = "next"
NRPS_MEMBERS_KEY = "members"
NRPS_CONTEXT_KEY = "context"
NRPS_CONTEXT_ID_KEY = "id"
NRPS_MEMBER_STATUS_KEY = "status"
NRPS_MEMBER_EMAIL_KEY = "email"
NRPS_MEMBER_NAME_KEY = "name"
NRPS_MEMBER_ROLES_KEY = "roles"
NRPS_MEMBER_MESSAGE_KEY = "message"
NRPS_MEMBER_ACTIVE_STATUS = "active"
NRPS_RESOURCE_LINK_QUERY_KEY = "rlid"

LTI_INSTRUCTOR_ROLES = {
    "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
    "http://purl.imsglobal.org/vocab/lis/v2/membership#ContentDeveloper",
}
LTI_STUDENT_ROLES = {
    "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner",
    "http://purl.imsglobal.org/vocab/lis/v2/membership#Mentor",
}
LTI_ADMIN_ROLES = {
    "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator",
}

CLIENT_ASSERTION_EXPIRY_SECONDS = 60 * 5
NRPS_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS = 60
NRPS_ACCESS_TOKEN_FALLBACK_TTL_SECONDS = 60
CANVAS_CONNECT_SYNC_WAIT_DEFAULT_SECONDS = 60 * 10
