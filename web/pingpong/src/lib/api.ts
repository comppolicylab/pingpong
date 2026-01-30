import { browser } from '$app/environment';
import { TextLineStream, JSONStream } from '$lib/streams';
import { getAnonymousSessionToken, getAnonymousShareToken } from '$lib/stores/anonymous';

/**
 * HTTP methods.
 */
export type Method = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';

/**
 * General fetcher type.
 */
export type Fetcher = typeof fetch;

/**
 * Base data type for all API responses.
 */
export type BaseData = Record<string, unknown>;

/**
 * Base Response type for all API responses.
 */
export type BaseResponse = {
	$status: number;
	detail?: string;
};

/**
 * Error data.
 */
export type Error = {
	detail?: string;
};

export type ValidationError = {
	detail: {
		loc: string[];
		msg: string;
		type: string;
	}[];
};

export class PresendError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'PresendError';
	}
}

export class RunActiveError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'RunActiveError';
	}
}

export class StreamError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'StreamError';
	}
}

/**
 * Error response. The $status will be >= 400.
 */
export type ErrorResponse = Error & BaseResponse;
export type ValidationErrorResponse = ValidationError & BaseResponse;

/**
 * Check whether a response is an error.
 */
export const isErrorResponse = (r: unknown): r is ErrorResponse => {
	return !!r && Object.hasOwn(r, '$status') && (r as BaseResponse).$status >= 400;
};

export const isValidationError = (r: unknown): r is ValidationErrorResponse => {
	if (!!r && Object.hasOwn(r, '$status') && (r as BaseResponse).$status === 422) {
		const detail = (r as ValidationError).detail;
		// Check if the detail is an array and contains objects with "type" and "msg" keys.
		if (Array.isArray(detail) && detail.every((item) => item.type && item.msg)) {
			return true;
		}
	}
	return false;
};

/**
 * Expand a response into its error and data components.
 */
export const expandResponse = <R extends BaseData>(
	r: BaseResponse & (Error | ValidationError | R)
) => {
	const $status = r.$status || 200;
	if (isValidationError(r)) {
		const detail = (r as ValidationError).detail;
		const error = detail
			.map((error) => {
				const location = error.loc.join(' -> '); // Join location array with arrow for readability
				return `Error at ${location}: ${error.msg}`;
			})
			.join('\n'); // Join all error messages with newlines
		return { $status, error: { detail: error } as Error, data: null };
	} else if (isErrorResponse(r)) {
		return { $status, error: r as Error, data: null };
	} else {
		return { $status, error: null, data: r as R };
	}
};

/**
 * Return response data or throw an error if one occurred.
 */
export const explodeResponse = <R extends BaseData>(
	r: BaseResponse & (Error | ValidationError | R)
) => {
	if (isValidationError(r)) {
		const detail = (r as ValidationError).detail;
		throw detail
			.map((error) => {
				const location = error.loc.join(' -> '); // Join location array with arrow for readability
				return `Error at ${location}: ${error.msg}`;
			})
			.join('\n'); // Join all error messages with newlines
	} else if (isErrorResponse(r)) {
		throw r;
	} else {
		return r as R;
	}
};

/**
 * Generic response returned by some API endpoints.
 */
export type GenericStatus = {
	status: string;
};

/**
 * Join URL parts with a slash.
 */
export const join = (...parts: string[]) => {
	let full = '';
	for (const part of parts) {
		if (full) {
			if (!full.endsWith('/')) {
				full += '/';
			}
			full += part.replace(/^\/+/, '');
		} else {
			full = part;
		}
	}
	return full;
};

/**
 * Get full API route.
 */
export const fullPath = (path: string) => {
	return join('/api/v1/', path);
};

let _ltiSessionToken: string | null = null;

export const setLTISessionToken = (token: string) => {
	if (browser) {
		sessionStorage.setItem('lti_session', token);
	}
	_ltiSessionToken = token;
};

export const hasLTISessionToken = () => {
	if (!browser) {
		return _ltiSessionToken !== null;
	}
	const token = sessionStorage.getItem('lti_session');
	return token !== null;
};

export const getLTISessionToken = () => {
	if (!browser) {
		return _ltiSessionToken;
	}
	return sessionStorage.getItem('lti_session');
};

export const clearLTISessionToken = () => {
	_ltiSessionToken = null;
	if (browser) {
		sessionStorage.removeItem('lti_session');
	}
};

/**
 * Common fetch method.
 */
const _fetch = async (
	f: Fetcher,
	method: Method,
	path: string,
	headers?: Record<string, string>,
	body?: string | FormData
) => {
	const full = fullPath(path);
	const anonymousSessionToken = getAnonymousSessionToken();
	if (anonymousSessionToken) {
		// If we have a session token for anonymous threads, add it to the headers.
		headers = {
			...headers,
			'X-Anonymous-Thread-Session': anonymousSessionToken
		};
	}
	// If we're in an LTI context, include the session token in the Authorization header.
	// This is needed because third-party cookies may be blocked in iframes.
	const ltiToken = getLTISessionToken();
	if (ltiToken) {
		headers = {
			...headers,
			Authorization: `Bearer ${ltiToken}`
		};
	}
	return f(full, {
		method,
		headers,
		body,
		credentials: 'include',
		mode: 'cors'
	});
};

/**
 * Common fetch method returning a JSON response.
 */
const _fetchJSON = async <R extends BaseData>(
	f: Fetcher,
	method: Method,
	path: string,
	headers?: Record<string, string>,
	body?: string | FormData
): Promise<(R | Error | ValidationError) & BaseResponse> => {
	const anonymousSessionToken = getAnonymousSessionToken();
	if (anonymousSessionToken) {
		// If we have a session token for anonymous threads, add it to the headers.
		headers = {
			...headers,
			'X-Anonymous-Thread-Session': anonymousSessionToken
		};
	}
	const res = await _fetch(f, method, path, headers, body);

	let data: BaseData = {};

	try {
		data = await res.json();
	} catch {
		// Do nothing
	}

	return { $status: res.status, ...data } as (R | Error) & BaseResponse;
};

/**
 * Method that passes data in the query string.
 */
const _qmethod = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	method: 'GET' | 'DELETE',
	path: string,
	data?: T
) => {
	// Treat args the same as when passed in the body.
	// Specifically, we want to remove "undefined" values.
	const filtered = data && (JSON.parse(JSON.stringify(data)) as Record<string, string>);
	const params = new URLSearchParams(filtered);
	const anonymousShareToken = getAnonymousShareToken();
	let headers: Record<string, string> = {};
	if (anonymousShareToken) {
		headers = {
			...headers,
			'X-Anonymous-Link-Share': anonymousShareToken
		};
	}
	path = `${path}?${params}`;
	return await _fetchJSON<R>(f, method, path, headers);
};

/**
 * Method that passes data in the body.
 */
const _bmethod = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	method: 'POST' | 'PUT' | 'PATCH',
	path: string,
	data?: T
) => {
	const body = JSON.stringify(data);
	let headers: Record<string, string> = { 'Content-Type': 'application/json' };
	const anonymousShareToken = getAnonymousShareToken();
	if (anonymousShareToken) {
		headers = {
			...headers,
			'X-Anonymous-Link-Share': anonymousShareToken
		};
	}
	return await _fetchJSON<R>(f, method, path, headers, body);
};

/**
 * Query with GET.
 */
const GET = async <T extends BaseData, R extends BaseData>(f: Fetcher, path: string, data?: T) => {
	return await _qmethod<T, R>(f, 'GET', path, data);
};

/**
 * Query with DELETE.
 */
const DELETE = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	path: string,
	data?: T
) => {
	return await _qmethod<T, R>(f, 'DELETE', path, data);
};

/**
 * Query with POST.
 */
const POST = async <T extends BaseData, R extends BaseData>(f: Fetcher, path: string, data?: T) => {
	return await _bmethod<T, R>(f, 'POST', path, data);
};

/**
 * Query with PUT.
 */
const PUT = async <T extends BaseData, R extends BaseData>(f: Fetcher, path: string, data?: T) => {
	return await _bmethod<T, R>(f, 'PUT', path, data);
};

/**
 * Query with PATCH.
 */
const PATCH = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	path: string,
	data?: T
) => {
	return await _bmethod<T, R>(f, 'PATCH', path, data);
};

/**
 * Information about an institution.
 */
export type Institution = {
	id: number;
	name: string;
	description: string | null;
	logo: string | null;
	default_api_key_id: number | null;
	created: string;
	updated: string | null;
};

export type LTIPublicInstitution = {
	id: number;
	name: string;
};

export type LTIPublicInstitutions = {
	institutions: LTIPublicInstitution[];
};

export type InstitutionAdmin = {
	id: number;
	email: string | null;
	first_name: string | null;
	last_name: string | null;
	display_name: string | null;
	name?: string | null;
	has_real_name?: boolean;
};

export type InstitutionWithAdmins = Institution & {
	admins: InstitutionAdmin[];
	root_admins: InstitutionAdmin[];
};

/**
 * Overall status of the session.
 */
export type SessionStatus = 'valid' | 'invalid' | 'missing' | 'error' | 'anonymous';

/**
 * Token information.
 */
export type SessionToken = {
	sub: string;
	exp: number;
	iat: number;
};

/**
 * Email with image.
 */
export type Profile = {
	name: string | null;
	email: string;
	gravatar_id: string;
	image_url: string;
};

/**
 * User activation state.
 */
export type UserState = 'unverified' | 'verified' | 'banned';

/**
 * Mapping from user to class, with extra information.
 */
export type UserClassRole = {
	user_id: number;
	class_id: number;
	role: string;
	from_canvas: boolean;
};

/**
 * List of user roles in a class.
 */
export type UserClassRoles = {
	roles: UserClassRole[];
};

/**
 * External Login Provider Information
 */
export type ExternalLoginProvider = {
	id: number;
	name: string;
	display_name: string | null;
	description: string | null;
};

export type ExternalLoginProviders = {
	providers: ExternalLoginProvider[];
};

/**
 * Get all external login providers.
 */
export const getExternalLoginProvidersForLTI = async (f: Fetcher) => {
	return await GET<never, ExternalLoginProviders>(f, 'lti/sso/providers');
};

export type LTIPublicSSOProvider = {
	id: number;
	name: string;
	display_name: string | null;
};

export type LTIPublicSSOProviders = {
	providers: LTIPublicSSOProvider[];
};

export const getPublicExternalLoginProvidersForLTI = async (f: Fetcher) => {
	return await GET<never, LTIPublicSSOProviders>(f, 'lti/public/sso/providers');
};

export const LTI_SSO_FIELDS = [
	'canvas.sisIntegrationId',
	'canvas.sisSourceId',
	'person.sourcedId'
] as const;
export type LTISSOField = (typeof LTI_SSO_FIELDS)[number];

export type LTIRegisterRequest = {
	name: string;
	admin_name: string;
	admin_email: string;
	provider_id: number;
	sso_field: LTISSOField | null;
	openid_configuration: string;
	registration_token: string;
	institution_ids?: number[];
	show_in_course_navigation?: boolean;
};

export const registerLTIInstance = async (f: Fetcher, data: LTIRegisterRequest) => {
	return await POST<LTIRegisterRequest, never>(f, 'lti/register', data);
};

export type ExternalLogin = {
	id: number;
	provider: string;
	identifier: string;
	provider_obj: ExternalLoginProvider;
};

/**
 * User information.
 */
export type AppUser = {
	id: number;
	/**
	 * `name` is a field we can rely on to display some identifier for the user.
	 *
	 * Unlike `first_name`, `last_name`, and `display_name`, `name` is always
	 * defined. As a fallback it will be defined as the email address.
	 */
	name: string;
	/**
	 * First or given name of the user.
	 */
	first_name: string | null;
	/**
	 * Last or family name of the user.
	 */
	last_name: string | null;
	/**
	 * Chosen name to display in lieu of first/last name.
	 */
	display_name: string | null;
	/**
	 * Email address of the user.
	 */
	email: string;
	/**
	 * Verification state of the user.
	 */
	state: UserState;
	/**
	 * Classes the user is in.
	 */
	classes: UserClassRole[];
	/**
	 * Institutions the user belongs to.
	 */
	institutions: Institution[];
	/**
	 * User account creation time.
	 */
	created: string;
	/**
	 * Last update to user account.
	 */
	updated: string | null;

	external_logins: ExternalLogin[];
};

/**
 * Information about the current session.
 */
export type SessionState = {
	status: SessionStatus;
	error: string | null;
	token: SessionToken | null;
	user: AppUser | null;
	profile: Profile | null;
	agreement_id: number | null;
};

/**
 * Information about a file uploaded to the server.
 */
export type ServerFile = {
	id: number;
	name: string;
	file_id: string;
	vision_obj_id: number | null;
	file_search_file_id: string | null;
	code_interpreter_file_id: string | null;
	vision_file_id: string | null;
	content_type: string;
	private: boolean | null;
	uploader_id: number | null;
	created: string;
	updated: string | null;
	image_description?: string | null;
};

/**
 * List of files.
 */
export type ServerFiles = {
	files: ServerFile[];
};

/*
 * Information about an image proxy.
 */
export type ImageProxy = {
	name: string;
	content_type: string;
	description: string;
	complements: string | null;
};

/**
 * Get the current user.
 */
export const me = async (f: Fetcher) => {
	return await GET<never, SessionState>(f, 'me');
};

/**
 * Permissions check request.
 */
export type GrantQuery = {
	target_type: string;
	target_id: number;
	relation: string;
};

/**
 * List of permissions check requests.
 */
export type GrantsQuery = {
	grants: GrantQuery[];
};

/**
 * Convenience type for giving grants names.
 */
export type NamedGrantsQuery = {
	[name: string]: GrantQuery;
};

/**
 * Information about a grant.
 */
export type GrantDetail = {
	request: GrantQuery;
	verdict: boolean;
};

/**
 * Information about a series of grants.
 */
export type Grants = {
	grants: GrantDetail[];
};

/**
 * Convenience type for seeing named grant verdicts.
 */
export type NamedGrants = {
	[name: string]: boolean;
};

/**
 * Get grants for the current user.
 */
export const grants = async <T extends NamedGrantsQuery>(
	f: Fetcher,
	query: T
): Promise<{ [name in keyof T]: boolean }> => {
	const grantNames = Object.keys(query);
	const grants = grantNames.map((name) => query[name]);

	const results = await POST<GrantsQuery, Grants>(f, 'me/grants', { grants });
	const expanded = expandResponse(results);
	if (expanded.error) {
		throw expanded.error;
	}

	const verdicts: NamedGrants = {};
	for (let i = 0; i < grantNames.length; i++) {
		verdicts[grantNames[i]] = expanded.data.grants[i].verdict;
	}
	return verdicts as { [name in keyof T]: boolean };
};

/**
 * Parameters for listing objects that the user has a grant for.
 */
export type GrantsListQuery = {
	rel: string;
	obj: string;
};

/**
 * List of objects that the user has a grant for.
 */
export type GrantsList = {
	subject_type: string;
	subject_id: number;
	target_type: string;
	relation: string;
	target_ids: number[];
};

/**
 * Get a list of objects that the user has a grant for.
 */
export const grantsList = async (f: Fetcher, relation: string, targetType: string) => {
	const result = await GET<GrantsListQuery, GrantsList>(f, 'me/grants/list', {
		obj: targetType,
		rel: relation
	});

	const expanded = expandResponse(result);
	if (expanded.error) {
		throw expanded.error;
	}

	return expanded.data.target_ids;
};

/**
 * List of institutions.
 */
export type Institutions = {
	institutions: Institution[];
};

export type InstitutionWithAdminsResponse = InstitutionWithAdmins;

/**
 * Parameters for a new institution.
 */
export type CreateInstitutionRequest = {
	name: string;
};

export type UpdateInstitutionRequest = {
	name?: string;
};

export type CopyInstitutionRequest = {
	name: string;
};

/**
 * Create a new institution.
 */
export const createInstitution = async (f: Fetcher, data: CreateInstitutionRequest) => {
	return await POST<CreateInstitutionRequest, Institution>(f, 'institution', data);
};

/**
 * Parameters for querying institutions.
 */
export type GetInstitutionsRequest = {
	role?: string;
};

/**
 * Get all institutions.
 */
export const getInstitutions = async (f: Fetcher, role?: string) => {
	const q: GetInstitutionsRequest = {};
	if (role) {
		q.role = role;
	}
	return await GET<GetInstitutionsRequest, Institutions>(f, 'institutions', q);
};

export const getPublicInstitutionsForLTI = async (f: Fetcher) => {
	return await GET<never, LTIPublicInstitutions>(f, 'lti/public/institutions');
};

/**
 * Get an institution by ID.
 */
export const getInstitution = async (f: Fetcher, id: string) => {
	return await GET<never, Institution>(f, `institution/${id}`);
};

export const getInstitutionsWithAdmins = async (f: Fetcher) => {
	return await GET<never, Institutions>(f, 'admin/institutions');
};

export const getInstitutionWithAdmins = async (f: Fetcher, id: number | string) => {
	return await GET<never, InstitutionWithAdminsResponse>(f, `admin/institutions/${id}`);
};

export const copyInstitution = async (f: Fetcher, id: number, data: CopyInstitutionRequest) => {
	return await POST<CopyInstitutionRequest, Institution>(f, `admin/institutions/${id}/copy`, data);
};

export const updateInstitution = async (f: Fetcher, id: number, data: UpdateInstitutionRequest) => {
	return await PATCH<UpdateInstitutionRequest, Institution>(f, `institution/${id}`, data);
};

export type SetInstitutionDefaultApiKeyRequest = {
	default_api_key_id: number | null;
};

export const setInstitutionDefaultApiKey = async (
	f: Fetcher,
	id: number,
	data: SetInstitutionDefaultApiKeyRequest
) => {
	return await PATCH<SetInstitutionDefaultApiKeyRequest, Institution>(
		f,
		`admin/institutions/${id}/default_api_key`,
		data
	);
};

export type AddInstitutionAdminRequest = {
	email: string;
};

export type InstitutionAdminResponse = {
	institution_id: number;
	user_id: number;
	email: string;
	added_admin: boolean;
};

export const addInstitutionAdmin = async (
	f: Fetcher,
	id: number,
	data: AddInstitutionAdminRequest
) => {
	return await POST<AddInstitutionAdminRequest, InstitutionAdminResponse>(
		f,
		`institution/${id}/admin`,
		data
	);
};

export const removeInstitutionAdmin = async (f: Fetcher, instId: number, userId: number) => {
	return await DELETE<never, GenericStatus>(f, `institution/${instId}/admin/${userId}`);
};

export type LTIRegistrationReviewStatus = 'pending' | 'approved' | 'rejected';

export type LTIRegistrationInstitution = {
	id: number;
	name: string;
};

export type LTIRegistrationReviewer = {
	id: number;
	email: string | null;
	first_name: string | null;
	last_name: string | null;
	display_name: string | null;
};

export type LTIRegistration = {
	id: number;
	issuer: string;
	client_id: string | null;
	auth_login_url: string;
	auth_token_url: string;
	key_set_url: string;
	token_algorithm: string;
	lms_platform: string | null;
	canvas_account_name: string | null;
	admin_name: string | null;
	admin_email: string | null;
	friendly_name: string | null;
	enabled: boolean;
	review_status: LTIRegistrationReviewStatus;
	internal_notes: string | null;
	review_notes: string | null;
	review_by: LTIRegistrationReviewer | null;
	institutions: LTIRegistrationInstitution[];
	created: string;
	updated: string | null;
};

export type LTIRegistrations = {
	registrations: LTIRegistration[];
};

export type LTIRegistrationDetail = LTIRegistration & {
	openid_configuration: string | null;
	registration_data: string | null;
	lti_classes_count: number;
};

export type UpdateLTIRegistrationRequest = {
	friendly_name?: string | null;
	admin_name?: string | null;
	admin_email?: string | null;
	internal_notes?: string | null;
	review_notes?: string | null;
};

export type SetLTIRegistrationStatusRequest = {
	review_status: LTIRegistrationReviewStatus;
};

export type SetLTIRegistrationEnabledRequest = {
	enabled: boolean;
};

export const getLTIRegistrations = async (f: Fetcher) => {
	return await GET<never, LTIRegistrations>(f, 'admin/lti/registrations');
};

export const getLTIRegistration = async (f: Fetcher, id: number | string) => {
	return await GET<never, LTIRegistrationDetail>(f, `admin/lti/registrations/${id}`);
};

export const updateLTIRegistration = async (
	f: Fetcher,
	id: number,
	data: UpdateLTIRegistrationRequest
) => {
	return await PATCH<UpdateLTIRegistrationRequest, LTIRegistration>(
		f,
		`admin/lti/registrations/${id}`,
		data
	);
};

export const setLTIRegistrationStatus = async (
	f: Fetcher,
	id: number,
	data: SetLTIRegistrationStatusRequest
) => {
	return await PATCH<SetLTIRegistrationStatusRequest, LTIRegistration>(
		f,
		`admin/lti/registrations/${id}/status`,
		data
	);
};

export const setLTIRegistrationEnabled = async (
	f: Fetcher,
	id: number,
	data: SetLTIRegistrationEnabledRequest
) => {
	return await PATCH<SetLTIRegistrationEnabledRequest, LTIRegistration>(
		f,
		`admin/lti/registrations/${id}/enabled`,
		data
	);
};

export type SetLTIRegistrationInstitutionsRequest = {
	institution_ids: number[];
};

export const setLTIRegistrationInstitutions = async (
	f: Fetcher,
	id: number,
	data: SetLTIRegistrationInstitutionsRequest
) => {
	return await PATCH<SetLTIRegistrationInstitutionsRequest, LTIRegistration>(
		f,
		`admin/lti/registrations/${id}/institutions`,
		data
	);
};

export type InstitutionsWithDefaultAPIKey = {
	institutions: Institution[];
};

export const getInstitutionsWithDefaultAPIKey = async (f: Fetcher) => {
	return await GET<never, InstitutionsWithDefaultAPIKey>(f, '/admin/lti/institutions');
};

export type LTISetupInstitution = {
	id: number;
	name: string;
};

export type LTISetupContext = {
	lti_class_id: number;
	course_name: string | null;
	course_code: string | null;
	course_term: string | null;
	institutions: LTISetupInstitution[];
};

export type LTILinkableGroup = {
	id: number;
	name: string;
	term: string;
	institution_name: string;
};

export type LTILinkableGroupsResponse = {
	groups: LTILinkableGroup[];
};

export type LTISetupCreateRequest = {
	institution_id: number;
	name: string;
	term: string;
};

export type LTISetupCreateResponse = {
	class_id: number;
};

export type LTISetupLinkRequest = {
	class_id: number;
};

export type LTISetupLinkResponse = {
	class_id: number;
};

export const getLTISetupContext = async (f: Fetcher, ltiClassId: number) => {
	return await GET<never, LTISetupContext>(f, `lti/setup/${ltiClassId}`);
};

export const getLTILinkableGroups = async (f: Fetcher, ltiClassId: number) => {
	return await GET<never, LTILinkableGroupsResponse>(f, `lti/setup/${ltiClassId}/linkable-groups`);
};

export const createLTIGroup = async (
	f: Fetcher,
	ltiClassId: number,
	data: LTISetupCreateRequest
) => {
	return await POST<LTISetupCreateRequest, LTISetupCreateResponse>(
		f,
		`lti/setup/${ltiClassId}/create`,
		data
	);
};

export const linkLTIGroup = async (f: Fetcher, ltiClassId: number, data: LTISetupLinkRequest) => {
	return await POST<LTISetupLinkRequest, LTISetupLinkResponse>(
		f,
		`lti/setup/${ltiClassId}/link`,
		data
	);
};

export type LMSStatus = 'authorized' | 'none' | 'error' | 'linked' | 'dismissed';

/**
 * Information about an individual class.
 */
export type Class = {
	id: number;
	name: string;
	term: string;
	institution_id: number;
	institution: Institution | null;
	created: string;
	updated: string | null;
	private: boolean | null;
	lms_user: AppUser | null;
	lms_type: LMSType | null;
	lms_tenant: string | null;
	lms_status: LMSStatus | null;
	lms_class: LMSClass | null;
	lms_last_synced: string | null;
	any_can_create_assistant: boolean | null;
	any_can_publish_assistant: boolean | null;
	any_can_publish_thread: boolean | null;
	any_can_upload_class_file: boolean | null;
	any_can_share_assistant: boolean | null;
	download_link_expiration: string | null;
	last_rate_limited_at: string | null;
	ai_provider: 'openai' | 'azure' | null;
};

/**
 * List of classes.
 */
export type Classes = {
	classes: Class[];
};

/**
 * Get all the classes at an institution.
 */
export const getClasses = async (f: Fetcher, id: string) => {
	return await GET<never, Classes>(f, `institution/${id}/classes`);
};

/**
 * Get classes visible to the current user.
 */
export const getMyClasses = async (f: Fetcher) => {
	return await GET<never, Classes>(f, `classes`);
};

/**
 * Information about all PingPong stats.
 */

export type Statistics = {
	institutions: number;
	classes: number;
	users: number;
	enrollments: number;
	assistants: number;
	threads: number;
	files: number;
};

export type StatisticsResponse = {
	statistics: Statistics;
};

/**
 * Get all PingPong stats.
 */
export const getStatistics = async (f: Fetcher) => {
	return await GET<never, StatisticsResponse>(f, `stats`);
};

/**
 * Parameters for creating a new class.
 */
export type CreateClassRequest = {
	name: string;
	term: string;
	private?: boolean;
	api_key_id: number | null;
	any_can_create_assistant?: boolean;
	any_can_publish_assistant?: boolean;
	any_can_share_assistant?: boolean;
	any_can_publish_thread?: boolean;
	any_can_upload_class_file?: boolean;
};

/**
 * Parameters for updating a class.
 */
export type UpdateClassRequest = {
	name?: string;
	term?: string;
	private?: boolean;
	any_can_create_assistant?: boolean;
	any_can_publish_assistant?: boolean;
	any_can_share_assistant?: boolean;
	any_can_publish_thread?: boolean;
	any_can_upload_class_file?: boolean;
};

export type TransferClassRequest = {
	institution_id: number;
};

export type CopyClassRequestInfo = {
	groupName: string;
	groupSession: string;
	institutionId: number | null;
	makePrivate: boolean;
	anyCanPublishThread: boolean;
	anyCanShareAssistant: boolean;
	assistantPermissions: string;
	assistantCopy: 'moderators' | 'all';
	userCopy: 'moderators' | 'all';
};

export type CopyClassRequest = {
	name: string;
	term: string;
	private: boolean;
	any_can_create_assistant: boolean;
	any_can_publish_assistant: boolean;
	any_can_share_assistant: boolean;
	any_can_publish_thread: boolean;
	any_can_upload_class_file: boolean;
	copy_assistants: 'moderators' | 'all';
	copy_users: 'moderators' | 'all';
	institution_id?: number | null;
};

/**
 * Create a new class.
 */
export const createClass = async (f: Fetcher, instId: number, data: CreateClassRequest) => {
	const url = `institution/${instId}/class`;
	return await POST<CreateClassRequest, Class>(f, url, data);
};

/**
 * Parameters for updating a class.
 */
export const updateClass = async (f: Fetcher, classId: number, data: UpdateClassRequest) => {
	const url = `class/${classId}`;
	return await PUT<UpdateClassRequest, Class>(f, url, data);
};

/**
 * Transfer a class to another institution.
 */
export const transferClass = async (f: Fetcher, classId: number, data: TransferClassRequest) => {
	const url = `class/${classId}/transfer`;
	return await POST<TransferClassRequest, Class>(f, url, data);
};

/**
 * Delete a new class.
 */
export const deleteClass = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Copy a class.
 */
export const copyClass = async (f: Fetcher, classId: number, data: CopyClassRequest) => {
	const url = `class/${classId}/copy`;
	return await POST<CopyClassRequest, Class>(f, url, data);
};

/**
 * Activity summary subscription info.
 */
export type ActivitySummarySubscription = {
	class_id: number;
	class_name: string;
	class_private: boolean;
	class_has_api_key: boolean;
	subscribed: boolean;
	last_email_sent: string | null;
	last_summary_empty: boolean;
};

export type ActivitySummarySubscriptionAdvancedOpts = {
	dna_as_join: boolean;
	dna_as_create: boolean;
};

/**
 * List of activity summary subscriptions.
 */
export type ActivitySummarySubscriptions = {
	subscriptions: ActivitySummarySubscription[];
	advanced_opts: ActivitySummarySubscriptionAdvancedOpts;
};

/**
 * Get all activity summary subscriptions.
 */
export const getActivitySummaries = async (f: Fetcher) => {
	return await GET<never, ActivitySummarySubscriptions>(f, 'me/activity_summaries');
};

export type ExternalLoginsResponse = {
	external_logins: ExternalLogin[];
};

export const getExternalLogins = async (f: Fetcher) => {
	return await GET<never, ExternalLoginsResponse>(f, 'me/external-logins');
};

/**
 * Information about a summary subscription.
 */

export type SummarySubscription = {
	subscribed: boolean;
};

/**
 * Get the summary subscription status for a class.
 */
export const getSummarySubscription = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/summarize/subscription`;
	return await GET<never, SummarySubscription>(f, url);
};

/**
 * Subscribe to the class summary.
 */
export const subscribeToSummary = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/summarize/subscription`;
	return await POST<never, GenericStatus>(f, url);
};

/**
 * Unsubscribe from the class summary.
 */
export const unsubscribeFromSummary = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/summarize/subscription`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Subscribe to all activity summaries.
 */
export const subscribeToAllSummaries = async (f: Fetcher) => {
	const url = 'me/activity_summaries';
	return await POST<never, GenericStatus>(f, url);
};

/**
 * Unsubscribe from all activity summaries.
 */
export const unsubscribeFromAllSummaries = async (f: Fetcher) => {
	const url = 'me/activity_summaries';
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Subscribe to all activity summaries when I create a group.
 */
export const subscribeToAllSummariesAtCreate = async (f: Fetcher) => {
	const url = 'me/activity_summaries/create';
	return await POST<never, GenericStatus>(f, url);
};

/**
 * Unsubscribe from all activity summaries.
 */
export const unsubscribeFromAllSummariesAtCreate = async (f: Fetcher) => {
	const url = 'me/activity_summaries/create';
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Subscribe to all activity summaries when I join a group.
 */
export const subscribeToAllSummariesAtJoin = async (f: Fetcher) => {
	const url = 'me/activity_summaries/join';
	return await POST<never, GenericStatus>(f, url);
};

/**
 * Unsubscribe from all activity summaries.
 */
export const unsubscribeFromAllSummariesAtJoin = async (f: Fetcher) => {
	const url = 'me/activity_summaries/join';
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 *  Information about an Activity Summary Request.
 *
 */
export type ActivitySummaryRequestOpts = {
	days: number;
};

export const requestActivitySummary = async (
	f: Fetcher,
	classId: number,
	data: ActivitySummaryRequestOpts
) => {
	const url = `class/${classId}/summarize`;
	return await POST<ActivitySummaryRequestOpts, GenericStatus>(f, url, data);
};

/**
 * Get all external login providers.
 */
export const getExternalLoginProviders = async (f: Fetcher) => {
	return await GET<never, ExternalLoginProviders>(f, 'admin/providers');
};

export type ExternalLoginProviderUpdateRequest = {
	display_name: string | null;
	description: string | null;
};

/**
 * Update an external login provider.
 */
export const updateExternalLoginProvider = async (
	f: Fetcher,
	providerId: number,
	data: ExternalLoginProviderUpdateRequest
) => {
	const url = `admin/providers/${providerId}`;
	return await PUT<ExternalLoginProviderUpdateRequest, GenericStatus>(f, url, data);
};

/**
 * Api key from the server.
 */
export type ApiKey = {
	api_key: string;
	provider?: string;
	endpoint?: string;
	api_version?: string;
	available_as_default?: boolean;
};

export type ApiKeyResponse = {
	api_key?: ApiKey;
};

export type UpdateApiKeyRequest = {
	api_key: string;
	provider: string;
	endpoint?: string;
	api_version?: string;
};

export type DefaultAPIKey = {
	id: number;
	redacted_key: string;
	name?: string;
	provider: string;
	endpoint?: string;
};

export type DefaultAPIKeys = {
	default_keys: DefaultAPIKey[];
};

/**
 * Get the default API keys.
 */
export const getDefaultAPIKeys = async (f: Fetcher) => {
	const url = 'api_keys/default';
	return await GET<never, DefaultAPIKeys>(f, url);
};

/**
 * Update the API key for a class.
 */
export const updateApiKey = async (
	f: Fetcher,
	classId: number,
	provider: string,
	apiKey: string,
	endpoint?: string
) => {
	const url = `class/${classId}/api_key`;
	return await PUT<UpdateApiKeyRequest, ApiKeyResponse>(f, url, {
		api_key: apiKey,
		provider: provider,
		endpoint: endpoint
	});
};

/**
 * Fetch the API key for a class.
 */
export const getApiKey = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/api_key`;
	return await GET<never, ApiKeyResponse>(f, url);
};

/**
 * Check if a class has an API key.
 */

export type ApiKeyCheck = {
	has_api_key: boolean;
};

export const hasAPIKey = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/api_key/check`;
	return await GET<never, ApiKeyCheck>(f, url);
};

/**
 * Language model information.
 */
export type AssistantModel = {
	id: string;
	created: string;
	owner: string;
	name: string;
	type: 'chat' | 'voice';
	description: string;
	is_latest: boolean;
	is_new: boolean;
	highlight: boolean;
	supports_vision: boolean;
	vision_support_override?: boolean;
	supports_file_search: boolean;
	supports_code_interpreter: boolean;
	supports_temperature: boolean;
	supports_classic_assistants: boolean;
	supports_next_gen_assistants: boolean;
	supports_minimal_reasoning_effort: boolean;
	supports_none_reasoning_effort: boolean;
	supports_verbosity: boolean;
	supports_web_search: boolean;
	supports_reasoning: boolean;
	supports_mcp_server: boolean;
	hide_in_model_selector?: boolean;
	reasoning_effort_levels?: number[];
	default_prompt_id?: string | null;
};

export type AssistantModelOptions = {
	value: string;
	name: string;
	description: string;
	supports_vision: boolean;
	supports_reasoning: boolean;
	is_new: boolean;
	highlight: boolean;
};

export type AssistantDefaultPrompt = {
	id: string;
	prompt: string;
};

/**
 * List of language models.
 */
export type AssistantModels = {
	models: AssistantModel[];
	default_prompts?: AssistantDefaultPrompt[];
	enforce_classic_assistants?: boolean;
};

export type AssistantModelLite = {
	id: string;
	supports_vision: boolean;
	azure_supports_vision: boolean;
	supports_reasoning: boolean;
};

export type AssistantModelLiteResponse = {
	models: AssistantModelLite[];
};

/**
 * Get models available with the api key for the class.
 */
export const getModels = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/models`;
	return await GET<never, AssistantModels>(f, url);
};

export const getModelsLite = async (f: Fetcher) => {
	const url = `models`;
	return await GET<never, AssistantModelLiteResponse>(f, url);
};

/**
 * Fetch a class by ID.
 */
export const getClass = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}`;
	return await GET<never, Class>(f, url);
};

/**
 * Fetch all files for a class.
 */
export const getClassFiles = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/files`;
	return await GET<never, ServerFiles>(f, url);
};

/**
 * List of threads.
 */
export type Threads = {
	threads: Thread[];
};

/**
 * Parameters for fetching threads.
 */
export type GetThreadsOpts = {
	limit?: number;
	before?: string;
};

/**
 * Get a list of threads.
 *
 * If `classId` is given, this will fetch the user's threads for that class.
 *
 * If `classId` is not given, this will fetch the user's recent threads from all classes.
 */
const getThreads = async (f: Fetcher, url: string, opts?: GetThreadsOpts) => {
	if (!opts) {
		opts = {};
	}

	// Ensure a limit is set. This prevents excessively large responses, and
	// also helps to determine when we've reached the last page of results.
	if (!opts.limit) {
		opts.limit = 20;
	}

	const result = expandResponse(await GET<GetThreadsOpts, Threads>(f, url, opts));

	if (result.error) {
		return {
			lastPage: true,
			threads: [] as Thread[],
			error: result.error
		};
	}

	let lastPage = false;
	// Add a flag to indicate if this is the last page of results.
	// If there was a requested limit and the server returned
	// fewer results, then we know we're on the last page.
	// If there was no limit, then the last page is when we get
	// an empty list of threads.
	if (opts?.limit) {
		lastPage = result.data.threads.length < opts.limit;
	} else {
		lastPage = result.data.threads.length === 0;
	}
	return {
		threads: result.data.threads,
		lastPage,
		error: null
	};
};

/**
 * Fetch all (visible) threads for a class.
 */
export const getClassThreads = async (f: Fetcher, classId: number, opts?: GetThreadsOpts) => {
	const url = `class/${classId}/threads`;
	return getThreads(f, url, opts);
};

/**
 * Get recent threads that the current user has participated in.
 */
export const getRecentThreads = async (f: Fetcher, opts?: GetThreadsOpts) => {
	return getThreads(f, 'threads/recent', opts);
};

/**
 * Options for fetching all threads.
 */
export type GetAllThreadsOpts = GetThreadsOpts & {
	class_id?: number;
	private?: boolean;
};

/**
 * Get all threads that the user can see.
 */
export const getAllThreads = async (f: Fetcher, opts?: GetAllThreadsOpts) => {
	return getThreads(f, 'threads', opts);
};

export type AnonymousLink = {
	id: number;
	name: string | null;
	share_token: string;
	active: boolean;
	activated_at: string | null;
	revoked_at: string | null;
};

/**
 * Information about an assistant.
 */
export type Assistant = {
	id: number;
	name: string;
	version?: number | null;
	description: string | null;
	notes: string | null;
	instructions: string;
	interaction_mode: 'chat' | 'voice';
	model: string;
	temperature: number | null;
	reasoning_effort: number | null;
	verbosity: number | null;
	tools: string;
	class_id: number;
	creator_id: number;
	published: string | null;
	use_latex: boolean | null;
	use_image_descriptions: boolean | null;
	hide_prompt: boolean | null;
	locked: boolean | null;
	assistant_should_message_first: boolean | null;
	should_record_user_information: boolean | null;
	allow_user_file_uploads: boolean | null;
	allow_user_image_uploads: boolean | null;
	hide_reasoning_summaries: boolean | null;
	hide_file_search_result_quotes: boolean | null;
	hide_file_search_document_names: boolean | null;
	hide_file_search_queries: boolean | null;
	hide_web_search_sources: boolean | null;
	hide_web_search_actions: boolean | null;
	hide_mcp_server_call_details: boolean | null;
	endorsed: boolean | null;
	created: string;
	updated: string | null;
	share_links: AnonymousLink[] | null;
};

/**
 * Information about assistant creators.
 */
export type AssistantCreators = {
	[id: number]: AppUser;
};

/**
 * Information about multiple assistants, plus metadata about creators.
 */
export type Assistants = {
	assistants: Assistant[];
	creators: AssistantCreators;
};

/**
 * Fetch all assistants for a class.
 */
export const getAssistants = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/assistants`;
	return await GET<never, Assistants>(f, url);
};

/**
 * Information about assistant files.
 */
export type AssistantFiles = {
	code_interpreter_files: ServerFile[];
	file_search_files: ServerFile[];
};

export type AssistantFilesResponse = {
	files: AssistantFiles;
};

/**
 * Fetch all files for a vector store.
 */
export const getAssistantFiles = async (f: Fetcher, classId: number, assistantId: number) => {
	const url = `/class/${classId}/assistant/${assistantId}/files`;
	return await GET<never, AssistantFilesResponse>(f, url);
};

/**
 * Get MCP servers configured for an assistant.
 */
export const getAssistantMCPServers = async (f: Fetcher, classId: number, assistantId: number) => {
	const url = `/class/${classId}/assistant/${assistantId}/mcp_servers`;
	return await GET<never, MCPServerToolsResponse>(f, url);
};

/**
 * OpenAI tool.
 */
export type Tool = {
	type: string;
};

/**
 * MCP Server authentication type.
 */
export type MCPAuthType = 'none' | 'token' | 'header';

/**
 * MCP Server input for create/update.
 */
export type MCPServerToolInput = {
	server_label?: string;
	display_name: string;
	server_url: string;
	auth_type: MCPAuthType;
	authorization_token?: string;
	headers?: Record<string, string>;
	description?: string;
	enabled: boolean;
};

/**
 * Response containing list of MCP servers.
 */
export type MCPServerToolsResponse = {
	mcp_servers: MCPServerToolInput[];
};

/**
 * Parameters for creating an assistant.
 */
export type CreateAssistantRequest = {
	name: string;
	description: string;
	instructions: string;
	notes: string;
	model: string;
	interaction_mode: 'chat' | 'voice';
	create_classic_assistant?: boolean;
	temperature: number | null;
	reasoning_effort: number | null;
	verbosity: number | null;
	tools: Tool[];
	code_interpreter_file_ids: string[];
	file_search_file_ids: string[];
	published?: boolean;
	use_latex?: boolean;
	use_image_descriptions?: boolean;
	hide_prompt?: boolean;
	deleted_private_files?: number[];
	assistant_should_message_first?: boolean;
	should_record_user_information?: boolean;
	allow_user_file_uploads?: boolean;
	allow_user_image_uploads?: boolean;
	hide_reasoning_summaries?: boolean;
	hide_file_search_result_quotes?: boolean;
	hide_file_search_document_names?: boolean;
	hide_file_search_queries?: boolean;
	hide_web_search_sources?: boolean;
	hide_web_search_actions?: boolean;
	hide_mcp_server_call_details?: boolean;
	mcp_servers?: MCPServerToolInput[];
};

export type CopyAssistantRequest = {
	name?: string | null;
	target_class_id?: number | null;
};

/**
 * Parameters for updating an assistant.
 */
export type UpdateAssistantRequest = {
	name?: string;
	description?: string;
	instructions?: string;
	notes?: string;
	model?: string;
	interaction_mode?: 'chat' | 'voice';
	create_classic_assistant?: boolean;
	temperature?: number | null;
	reasoning_effort?: number | null;
	verbosity?: number | null;
	tools?: Tool[];
	code_interpreter_file_ids?: string[];
	file_search_file_ids?: string[];
	published?: boolean;
	use_latex?: boolean;
	use_image_descriptions?: boolean;
	hide_prompt?: boolean;
	deleted_private_files?: number[];
	assistant_should_message_first?: boolean;
	should_record_user_information?: boolean;
	allow_user_file_uploads?: boolean;
	allow_user_image_uploads?: boolean;
	hide_reasoning_summaries?: boolean;
	hide_file_search_result_quotes?: boolean;
	hide_file_search_document_names?: boolean;
	hide_file_search_queries?: boolean;
	hide_web_search_sources?: boolean;
	hide_web_search_actions?: boolean;
	hide_mcp_server_call_details?: boolean;
	mcp_servers?: MCPServerToolInput[];
};

/**
 * Create a new assistant.
 */
export const createAssistant = async (
	f: Fetcher,
	classId: number,
	data: CreateAssistantRequest
) => {
	const url = `class/${classId}/assistant`;
	return await POST<CreateAssistantRequest, Assistant>(f, url, data);
};

/**
 * Update an existing assistant.
 */
export const updateAssistant = async (
	f: Fetcher,
	classId: number,
	assistantId: number,
	data: UpdateAssistantRequest
) => {
	const url = `class/${classId}/assistant/${assistantId}`;
	return await PUT<UpdateAssistantRequest, Assistant>(f, url, data);
};

/**
 * Copy an existing assistant to the same class or a different class.
 */
export const copyAssistant = async (
	f: Fetcher,
	classId: number,
	assistantId: number,
	data: CopyAssistantRequest = {}
) => {
	const url = `class/${classId}/assistant/${assistantId}/copy`;
	return await POST<CopyAssistantRequest, Assistant>(f, url, data);
};

export type CopyAssistantCheckResponse = {
	allowed: boolean;
};

/**
 * Check whether an assistant can be copied to a target class.
 */
export const copyAssistantCheck = async (
	f: Fetcher,
	classId: number,
	assistantId: number,
	data: CopyAssistantRequest
) => {
	const url = `class/${classId}/assistant/${assistantId}/copy/check`;
	return await POST<CopyAssistantRequest, CopyAssistantCheckResponse>(f, url, data);
};

export type AssistantInstructionsPreviewResponse = {
	instructions_preview: string;
};

export type AssistantInstructionsPreviewRequest = {
	instructions: string;
};

/**
 * Get a preview of an assistant's instructions.
 */
export const previewAssistantInstructions = async (
	f: Fetcher,
	classId: number,
	data: AssistantInstructionsPreviewRequest
) => {
	const url = `class/${classId}/assistant_instructions`;
	return await POST<AssistantInstructionsPreviewRequest, AssistantInstructionsPreviewResponse>(
		f,
		url,
		data
	);
};

/**
 * Publish an assistant.
 */
export const publishAssistant = async (f: Fetcher, classId: number, assistantId: number) => {
	const url = `class/${classId}/assistant/${assistantId}/publish`;
	return await POST<never, GenericStatus>(f, url);
};

/**
 * Unpublish an assistant.
 */
export const unpublishAssistant = async (f: Fetcher, classId: number, assistantId: number) => {
	const url = `class/${classId}/assistant/${assistantId}/publish`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Delete an assistant.
 */
export const deleteAssistant = async (f: Fetcher, classId: number, assistantId: number) => {
	const url = `class/${classId}/assistant/${assistantId}`;
	return await DELETE<never, GenericStatus>(f, url);
};

export const createAssistantShareLink = async (
	f: Fetcher,
	classId: number,
	assistantId: number
) => {
	const url = `class/${classId}/assistant/${assistantId}/share`;
	return await POST<never, GenericStatus>(f, url);
};

export type UpdateAssistantShareLinkNameRequest = {
	name: string;
};

export const updateAssistantShareLinkName = async (
	f: Fetcher,
	classId: number,
	assistantId: number,
	shareLinkId: number,
	data: UpdateAssistantShareLinkNameRequest
) => {
	const url = `class/${classId}/assistant/${assistantId}/share/${shareLinkId}`;
	return await PUT<UpdateAssistantShareLinkNameRequest, GenericStatus>(f, url, data);
};

export const deleteAssistantShareLink = async (
	f: Fetcher,
	classId: number,
	assistantId: number,
	shareLinkId: number
) => {
	const url = `class/${classId}/assistant/${assistantId}/share/${shareLinkId}`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * file upload options.
 */
export interface UploadOptions {
	onProgress?: (percent: number) => void;
}

export type FileUploadPurpose =
	| 'assistants'
	| 'vision'
	| 'fs_ci_multimodal'
	| 'fs_multimodal'
	| 'ci_multimodal';

/**
 * Upload a file to a class.
 */
export const uploadFile = (classId: number, file: File, opts?: UploadOptions) => {
	const url = fullPath(`class/${classId}/file`);
	return _doUpload(url, file, opts);
};

/**
 * Upload a private file to a class for the given user.
 */
export const uploadUserFile = (
	classId: number,
	userId: number,
	file: File,
	opts?: UploadOptions,
	purpose: FileUploadPurpose = 'assistants',
	useImageDescriptions: boolean = false
) => {
	const url = fullPath(`class/${classId}/user/${userId}/file`);
	return _doUpload(url, file, opts, purpose, useImageDescriptions);
};

/**
 * File upload error.
 */
export interface FileUploadFailure {
	error: {
		detail: string;
	};
}

/**
 * Result of a file upload.
 */
export type FileUploadResult = ServerFile | FileUploadFailure;

/**
 * Info about the file upload.
 */
export interface FileUploadInfo {
	file: File;
	promise: Promise<FileUploadResult>;
	state: 'pending' | 'success' | 'error' | 'deleting';
	response: FileUploadResult | null;
	progress: number;
}

/**
 * Wrapper function to call the file uploader more easily.
 *
 * Does not need to be used, but helpful for the UI.
 */
export type FileUploader = (
	file: File,
	progress: (p: number) => void,
	purpose: FileUploadPurpose,
	useImageDescriptions: boolean
) => FileUploadInfo;

/**
 * Wrapper function to call the file deleter more easily.
 *
 * Does not need to be used, but helpful for the UI.
 */
export type FileRemover = (fileId: number) => Promise<void>;

/**
 * Upload a file to the given endpoint.
 */
const _doUpload = (
	url: string,
	file: File,
	opts?: UploadOptions,
	purpose: FileUploadPurpose = 'assistants',
	useImageDescriptions: boolean = false
): FileUploadInfo => {
	if (!browser) {
		throw new Error('File uploads are not supported in this environment.');
	}

	const xhr = new XMLHttpRequest();

	const info: Omit<FileUploadInfo, 'promise'> = {
		file,
		state: 'pending',
		response: null,
		progress: 0
	};

	// Callback for upload progress updates.
	const onProgress = (e: ProgressEvent) => {
		if (e.lengthComputable) {
			const percent = (e.loaded / e.total) * 100;
			info.progress = percent;
			if (opts?.onProgress) {
				opts.onProgress(percent);
			}
		}
	};

	// Don't use the normal fetch because this only works with xhr, and we want
	// to be able to track progress.
	const promise = new Promise<FileUploadResult>((resolve, reject) => {
		xhr.open('POST', url, true);
		xhr.setRequestHeader('Accept', 'application/json');
		const anonymousSessionToken = getAnonymousSessionToken();
		if (anonymousSessionToken) {
			xhr.setRequestHeader('X-Anonymous-Thread-Session', anonymousSessionToken);
		}
		const anonymousShareToken = getAnonymousShareToken();
		if (anonymousShareToken) {
			xhr.setRequestHeader('X-Anonymous-Link-Share', anonymousShareToken);
		}
		// If we're in an LTI context, include the session token in the Authorization header.
		const ltiToken = getLTISessionToken();
		if (ltiToken) {
			xhr.setRequestHeader('Authorization', `Bearer ${ltiToken}`);
		}
		xhr.upload.onprogress = onProgress;
		xhr.onreadystatechange = () => {
			if (xhr.readyState === 4) {
				if (xhr.status < 300) {
					info.state = 'success';
					info.response = JSON.parse(xhr.responseText) as ServerFile;
					resolve(info.response);
				} else {
					info.state = 'error';
					if (xhr.responseText) {
						try {
							info.response = { error: JSON.parse(xhr.responseText) };
						} catch {
							info.response = { error: { detail: xhr.responseText } };
						}
					} else {
						info.response = { error: { detail: 'Unknown error.' } };
					}
					reject(info.response);
				}
			}
		};
	});
	const formData = new FormData();
	formData.append('upload', file);
	formData.append('purpose', purpose);
	if (useImageDescriptions === true) {
		formData.append('use_image_descriptions', 'true');
	}
	xhr.send(formData);

	return { ...info, promise };
};

/**
 * Delete a file.
 */
export const deleteFile = async (f: Fetcher, classId: number, fileId: number) => {
	const url = `class/${classId}/file/${fileId}`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Delete a thread file.
 */
export const deleteThreadFile = async (
	f: Fetcher,
	classId: number,
	threadId: number,
	fileId: string
) => {
	const url = `class/${classId}/thread/${threadId}/file/${fileId}`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Delete a user file.
 */
export const deleteUserFile = async (
	f: Fetcher,
	classId: number,
	userId: number,
	fileId: number
) => {
	const url = `class/${classId}/user/${userId}/file/${fileId}`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Information about a user's role in a class.
 */
export type ClassUserRoles = {
	admin: boolean;
	teacher: boolean;
	student: boolean;
};

/**
 * Information about a user inside of a class.
 */
export type ClassUser = {
	id: number;
	name: string | null;
	has_real_name: boolean;
	email: string;
	roles: ClassUserRoles;
	state: UserState;
	lms_tenant: string | null;
	lms_type: LMSType | null;
};

/**
 * List of users in a class.
 */
export type ClassUsers = {
	users: ClassUser[];
	limit: number;
	offset: number;
	total: number;
};

/**
 * Search parameters for getting users in a class.
 */
export type GetClassUsersOpts = {
	limit?: number;
	offset?: number;
	search?: string;
};

/**
 * Fetch users in a class.
 */
export const getClassUsers = async (f: Fetcher, classId: number, opts?: GetClassUsersOpts) => {
	const url = `class/${classId}/users`;

	const response = await GET<GetClassUsersOpts, ClassUsers>(f, url, opts);
	const expanded = expandResponse(response);
	if (expanded.error) {
		return {
			lastPage: true,
			users: [],
			error: expanded.error
		};
	}
	const lastPage = expanded.data.users.length < expanded.data.limit;

	return {
		...expanded.data,
		lastPage,
		error: null
	};
};

export type ClassSupervisors = {
	users: SupervisorUser[];
};

export type SupervisorUser = {
	name: string | null;
	email: string;
};

/**
 * Fetch teachers in a class.
 *
 */
export const getSupervisors = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/supervisors`;
	return await GET<never, ClassSupervisors>(f, url);
};

/**
 * Response type for getClassUsers.
 */
export type ClassUsersResponse = ReturnType<typeof getClassUsers>;

/**
 * Parameters for creating a new class user.
 */
export type CreateClassUserRequest = {
	email: string;
	display_name: string | null;
	roles: ClassUserRoles;
};

/**
 * Plural version of CreateClassUserRequest.
 */
export type CreateClassUsersRequest = {
	roles: CreateClassUserRequest[];
	silent: boolean;
};

export type EmailValidationResult = {
	email: string;
	valid: boolean;
	isUser: boolean;
	name: string | null;
	error: string | null;
};

export type EmailValidationRequest = {
	emails: string;
};

export type EmailValidationResults = {
	results: EmailValidationResult[];
};

export const validateEmails = async (f: Fetcher, classId: number, data: EmailValidationRequest) => {
	const url = `class/${classId}/user/validate`;
	return await POST<EmailValidationRequest, EmailValidationResults>(f, url, data);
};

export const revalidateEmails = async (
	f: Fetcher,
	classId: number,
	data: EmailValidationResults
) => {
	const url = `class/${classId}/user/revalidate`;
	return await POST<EmailValidationResults, EmailValidationResults>(f, url, data);
};

export type CreateUserResult = {
	email: string;
	display_name: string | null;
	error: string | null;
};

export type CreateUserResults = {
	results: CreateUserResult[];
};

/**
 * Create multiple class users.
 */
export const createClassUsers = async (
	f: Fetcher,
	classId: number,
	data: CreateClassUsersRequest
) => {
	const url = `class/${classId}/user`;
	return await POST<CreateClassUsersRequest, CreateUserResults>(f, url, data);
};

/**
 * Parameters for updating a class user.
 */
export type UpdateClassUserRoleRequest = {
	role: Role | null;
};

/**
 * Update a user's role in a class.
 */
export const updateClassUserRole = async (
	f: Fetcher,
	classId: number,
	userId: number,
	data: UpdateClassUserRoleRequest
) => {
	const url = `class/${classId}/user/${userId}/role`;
	return await PUT<UpdateClassUserRoleRequest, UserClassRole>(f, url, data);
};

/**
 * Remove a user from a class.
 */
export const removeClassUser = async (f: Fetcher, classId: number, userId: number) => {
	const url = `class/${classId}/user/${userId}`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Export class threads.
 */
export const exportThreads = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/export`;
	return await GET<never, GenericStatus>(f, url);
};

/**
 * Parameters for creating a new thread.
 */
export type CreateThreadRequest = {
	assistant_id: number;
	parties?: number[];
	message: string | null;
	tools_available: Tool[];
	file_search_file_ids?: string[];
	code_interpreter_file_ids?: string[];
	vision_file_ids?: string[];
	vision_image_descriptions?: ImageProxy[];
	timezone?: string | null;
	conversation_id?: string | null;
};

export type CreateAudioThreadRequest = {
	assistant_id: number;
	parties?: number[];
	timezone?: string | null;
	conversation_id?: string | null;
};

export type VoiceModeRecordingInfo = {
	recording_id: string;
	duration: number;
};

/**
 * Stream chunks from a thread recording.
 */
const streamThreadRecordingChunks = async (res: Response) => {
	if (res.status !== 200) {
		try {
			const errorData = await res.clone().json();
			return {
				async *[Symbol.asyncIterator]() {
					yield {
						type: 'error',
						detail: errorData.detail || 'We encountered an unexpected error.'
					};
				}
			};
		} catch {
			return {
				async *[Symbol.asyncIterator]() {
					yield {
						type: 'error',
						detail: 'Failed to download audio. We encountered an unexpected error.'
					};
				}
			};
		}
	}
	if (!res.body) {
		throw new Error('No response body');
	}
	const reader = res.body.getReader();

	return {
		async *[Symbol.asyncIterator]() {
			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				yield value!;
			}
		}
	};
};

/**
 * Get a thread Voice Mode recording.
 */
export const getThreadRecording = async (f: Fetcher, classId: number, threadId: number) => {
	const url = `class/${classId}/thread/${threadId}/recording`;
	const res = await _fetch(f, 'GET', url);
	return streamThreadRecordingChunks(res);
};

/**
 * Request a diarized transcription of a thread Voice Mode recording.
 *
 * This starts an async job and sends a download link via email when ready.
 */
export const transcribeThreadRecording = async (f: Fetcher, classId: number, threadId: number) => {
	const url = `class/${classId}/thread/${threadId}/recording/transcribe`;
	return await POST<Record<string, never>, GenericStatus>(f, url, {});
};

/**
 * Thread information.
 */
export type Thread = {
	id: number;
	name: string | null;
	version: number;
	interaction_mode: 'chat' | 'voice';
	class_id: number;
	assistant_names?: Record<number, string> | null;
	assistant_id: number;
	private: boolean;
	tools_available: string | null;
	user_names?: string[];
	created: string;
	last_activity: string;
	display_user_info?: boolean;
	anonymous_session?: boolean;
	is_current_user_participant?: boolean;
};

export type ThreadWithOptionalToken = {
	thread: Thread;
	session_token?: string | null;
};

/**
 * Create a new conversation thread.
 */
export const createThread = async (f: Fetcher, classId: number, data: CreateThreadRequest) => {
	const url = `class/${classId}/thread`;
	return await POST<CreateThreadRequest, ThreadWithOptionalToken>(f, url, data);
};

/**
 * Create voice mode thread.
 */
export const createAudioThread = async (
	f: Fetcher,
	classId: number,
	data: CreateAudioThreadRequest
) => {
	const url = `class/${classId}/thread/audio`;
	return await POST<CreateAudioThreadRequest, ThreadWithOptionalToken>(f, url, data);
};

/**
 * Delete a thread.
 */
export const deleteThread = async (f: Fetcher, classId: number, threadId: number) => {
	const url = `class/${classId}/thread/${threadId}`;
	return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Publish a thread.
 */
export const publishThread = async (f: Fetcher, classId: number, threadId: number) => {
	const url = `class/${classId}/thread/${threadId}/publish`;
	return await POST<never, GenericStatus>(f, url);
};

/**
 * Unpublish a thread.
 */
export const unpublishThread = async (f: Fetcher, classId: number, threadId: number) => {
	const url = `class/${classId}/thread/${threadId}/publish`;
	return await DELETE<never, GenericStatus>(f, url);
};

type LastError = {
	code: 'server_error' | 'rate_limit_exceeded';
	message: string;
};

/**
 * Type of a thread run, per the OpenAI library.
 */
export type OpenAIRun = {
	id: string;
	assistant_id: string;
	cancelled_at: number | null;
	completed_at: number | null;
	created_at: number;
	expires_at: number | null;
	failed_at: number | null;
	file_ids: string[];
	instructions: string;
	last_error: LastError | null;
	metadata: Record<string, unknown>;
	model: string;
	object: 'thread.run';
	//required_action: RequiredAction | null;
	started_at: number | null;
	status:
		| 'queued'
		| 'in_progress'
		| 'requires_action'
		| 'cancelling'
		| 'cancelled'
		| 'failed'
		| 'incomplete'
		| 'completed'
		| 'expired'
		| 'pending';
	tools: unknown[];
	// usage: unknown | null;
};

export type AttachmentTool = {
	type: 'file_search' | 'code_interpreter';
};

export type OpenAIAttachment = {
	file_id: string;
	tools: AttachmentTool[] | null;
};

export type TextAnnotationFilePathFilePath = {
	file_id: string;
};

export type TextAnnotationFilePath = {
	end_index: number;
	file_path: TextAnnotationFilePathFilePath;
	start_index: number;
	text: string;
	type: 'file_path';
};

export type TextAnnotationFileCitationFileCitation = {
	file_id: string;
	file_name: string;
	quote: string;
};

export type TextAnnotationFileCitation = {
	end_index: number;
	file_citation: TextAnnotationFileCitationFileCitation;
	start_index: number;
	text: string;
	type: 'file_citation';
};

export type TextAnnotationURLCitation = {
	end_index: number;
	start_index: number;
	title: string;
	type: 'url_citation';
	url: string;
};

export type TextAnnotation =
	| TextAnnotationFilePath
	| TextAnnotationFileCitation
	| TextAnnotationURLCitation;

export type Text = {
	annotations: TextAnnotation[];
	value: string;
};

export type MessageContentText = {
	text: Text;
	type: 'text';
};

export type ImageFile = {
	file_id: string;
};

export type MessageContentImageFile = {
	image_file: ImageFile;
	type: 'image_file';
};

export type MessageContentCodeOutputImageURL = {
	url: string;
	type: 'code_output_image_url';
};

export type MessageContentCodeOutputImageFile = {
	image_file: ImageFile;
	type: 'code_output_image_file';
};

export type MessageContentCodeOutputLogs = {
	logs: string;
	type: 'code_output_logs';
};

export type MessageContentCode = {
	code: string;
	type: 'code';
};

export type CodeInterpreterCallPlaceholder = {
	run_id: string;
	step_id: string;
	type: 'code_interpreter_call_placeholder';
};

export type FileSearchCallItem = {
	step_id: string;
	type: 'file_search_call';
	queries?: string[];
	status?: 'in_progress' | 'searching' | 'completed' | 'incomplete' | 'failed';
};

export type WebSearchSource = {
	url?: string | null;
	title?: string | null;
	type: 'url';
};

export type WebSearchCallItem = {
	step_id: string;
	type: 'web_search_call';
	action?: WebSearchAction | null;
	status: 'in_progress' | 'completed' | 'incomplete' | 'searching' | 'failed';
};

export type MCPToolCallStatus = 'in_progress' | 'completed' | 'incomplete' | 'calling' | 'failed';

export type MCPToolError = Record<string, unknown> | string;

export type MCPListToolsTool = {
	name: string;
	description?: string | null;
	input_schema?: Record<string, unknown> | null;
	annotations?: Record<string, unknown> | null;
};

export type MCPServerCallItem = {
	step_id: string;
	type: 'mcp_server_call';
	server_label: string;
	server_name?: string | null;
	tool_name?: string | null;
	arguments?: string | null;
	output?: string | null;
	error?: MCPToolError | null;
	status?: MCPToolCallStatus | null;
};

export type MCPListToolsCallItem = {
	step_id: string;
	type: 'mcp_list_tools_call';
	server_label: string;
	server_name?: string | null;
	tools?: MCPListToolsTool[];
	error?: MCPToolError | null;
	status?: MCPToolCallStatus | null;
};

export type ReasoningSummaryPart = {
	id?: number;
	part_index: number;
	summary_text: string;
};

export type ReasoningCallItem = {
	step_id: string;
	type: 'reasoning';
	summary: ReasoningSummaryPart[];
	status: 'in_progress' | 'completed' | 'incomplete';
	thought_for?: string | null;
};

export type Content =
	| MessageContentImageFile
	| MessageContentText
	| MessageContentCode
	| MessageContentCodeOutputImageFile
	| MessageContentCodeOutputImageURL
	| MessageContentCodeOutputLogs
	| CodeInterpreterCallPlaceholder
	| FileSearchCallItem
	| WebSearchCallItem
	| MCPServerCallItem
	| MCPListToolsCallItem
	| ReasoningCallItem;

export type OpenAIMessage = {
	id: string;
	assistant_id: string | null;
	content: Content[];
	created_at: number;
	output_index?: number;
	file_search_file_ids?: string[];
	code_interpreter_file_ids?: string[];
	vision_file_ids?: string[];
	metadata: Record<string, unknown> | null;
	object: 'thread.message' | 'code_interpreter_call_placeholder';
	message_type?:
		| 'file_search_call'
		| 'code_interpreter_call'
		| 'reasoning'
		| 'mcp_server_call'
		| 'mcp_list_tools_call'
		| null;
	role: 'user' | 'assistant';
	run_id: string | null;
	attachments: OpenAIAttachment[] | null;
};

/**
 * Accounting of individuals in a thread.
 */
export type ThreadParticipants = {
	user: string[];
	assistant: { [id: number]: string };
};

/**
 * Thread object with additional metadata.
 */
export type ThreadWithMeta = {
	thread: Thread;
	model: string;
	tools_available: string;
	run: OpenAIRun | null;
	limit: number;
	messages: OpenAIMessage[];
	ci_messages: OpenAIMessage[];
	fs_messages: OpenAIMessage[];
	ws_messages: OpenAIMessage[];
	mcp_messages: OpenAIMessage[];
	reasoning_messages: OpenAIMessage[];
	attachments: Record<string, ServerFile>;
	instructions: string | null;
	recording: VoiceModeRecordingInfo | null;
	has_more: boolean;
};

/**
 * Get a thread by ID.
 */
export const getThread = async (f: Fetcher, classId: number, threadId: number) => {
	const url = `class/${classId}/thread/${threadId}`;
	return await GET<never, ThreadWithMeta>(f, url);
};

export type CodeInterpreterMessages = {
	ci_messages: OpenAIMessage[];
};

export type GetCIMessagesOpts = {
	run_id: string;
	step_id: string;
};

/**
 * Get code interpreter messages based on placeholder.
 */
export const getCIMessages = async (
	f: Fetcher,
	classId: number,
	threadId: number,
	run_id: string,
	step_id: string
) => {
	const url = `class/${classId}/thread/${threadId}/ci_messages`;
	const opts = {
		run_id: run_id,
		step_id: step_id
	};
	const expanded = expandResponse(
		await GET<GetCIMessagesOpts, CodeInterpreterMessages>(f, url, opts)
	);
	if (expanded.error) {
		return {
			ci_messages: [],
			error: expanded.error
		};
	} else {
		return {
			ci_messages: expanded.data.ci_messages,
			error: null
		};
	}
};

/**
 * Parameters for getting messages in a thread.
 */
export type GetThreadMessagesOpts = {
	limit?: number;
	before?: string;
};

/**
 * Thread messages
 */
export type ThreadMessages = {
	messages: OpenAIMessage[];
	ci_messages: OpenAIMessage[];
	fs_messages: OpenAIMessage[];
	ws_messages: OpenAIMessage[];
	mcp_messages: OpenAIMessage[];
	reasoning_messages: OpenAIMessage[];
	limit: number;
	has_more: boolean;
};

/**
 * List messages in a thread.
 */
export const getThreadMessages = async (
	f: Fetcher,
	classId: number,
	threadId: number,
	opts?: GetThreadMessagesOpts
) => {
	const url = `class/${classId}/thread/${threadId}/messages`;
	const expanded = expandResponse(await GET<GetThreadMessagesOpts, ThreadMessages>(f, url, opts));
	if (expanded.error) {
		return {
			lastPage: true,
			limit: null,
			messages: [],
			fs_messages: [],
			ws_messages: [],
			mcp_messages: [],
			ci_messages: [],
			reasoning_messages: [],
			has_more: false,
			error: expanded.error
		};
	}

	const hasMore = expanded.data.has_more;
	const lastPage = !hasMore;
	return {
		messages: expanded.data.messages,
		ci_messages: expanded.data.ci_messages,
		fs_messages: expanded.data.fs_messages,
		ws_messages: expanded.data.ws_messages,
		mcp_messages: expanded.data.mcp_messages,
		reasoning_messages: expanded.data.reasoning_messages,
		limit: expanded.data.limit,
		has_more: hasMore,
		lastPage,
		error: null
	};
};

/**
 * Data for posting a new message to a thread.
 */
export type NewThreadMessageRequest = {
	message: string;
	file_search_file_ids?: string[];
	code_interpreter_file_ids?: string[];
	vision_file_ids?: string[];
	vision_image_descriptions?: ImageProxy[];
	timezone?: string;
};

/**
 * Thread with run information.
 */
export type ThreadRun = {
	thread: Thread;
	run: OpenAIRun;
};

export type OpenAIMessageDelta = {
	content: Content[];
	role: null; // TODO - is this correct?
	file_ids: string[] | null;
};

export type ThreadStreamMessageDeltaChunk = {
	type: 'message_delta';
	delta: OpenAIMessageDelta;
};

export type ThreadStreamMessageCreatedChunk = {
	type: 'message_created';
	role: 'user' | 'assistant';
	message: OpenAIMessage;
};

export type ToolImageOutput = {
	image: ImageFile;
	index: number;
	type: 'image';
};

export type ToolOutput =
	| ToolImageOutput
	| MessageContentCodeOutputImageURL
	| MessageContentCodeOutputLogs;

export type ToolCallIO = {
	input: string | null;
	outputs: Array<ToolOutput> | null;
};

export type CodeInterpreterCall = {
	code_interpreter: ToolCallIO;
	id: string;
	index: number;
	output_index?: number;
	type: 'code_interpreter';
	run_id: string | null;
};

export type FileSearchCall = {
	id: string;
	index: number;
	output_index?: number;
	type: 'file_search';
	queries: string[] | null;
	run_id: string | null;
	status: 'in_progress' | 'searching' | 'completed' | 'incomplete' | 'failed';
};

export type WebSearchActionSearchSource = {
	url: string;
	type: 'url';
};

export type WebSearchActionSearch = {
	type: 'search';
	query: string;
	sources: WebSearchActionSearchSource[];
};

export type WebSearchActionOpenPage = {
	type: 'open_page';
	url: string;
};

export type WebSearchActionFind = {
	type: 'find';
	pattern: string;
	url: string;
};

export type WebSearchAction = WebSearchActionSearch | WebSearchActionOpenPage | WebSearchActionFind;

export type WebSearchCall = {
	type: 'web_search';
	id: string;
	index: number;
	output_index?: number;
	run_id: string | null;
	action: WebSearchAction;
	status: 'in_progress' | 'completed' | 'incomplete' | 'failed' | 'searching';
};

export type McpCall = {
	type: 'mcp_call';
	id: string;
	index: number;
	output_index?: number;
	run_id?: string | null;
	server_label?: string | null;
	server_name?: string | null;
	name?: string | null;
	arguments?: string | null;
	arguments_delta?: string | null;
	output?: string | null;
	error?: MCPToolError | null;
	status?: MCPToolCallStatus | null;
};

export type McpListToolsCall = {
	type: 'mcp_list_tools';
	id: string;
	index: number;
	output_index?: number;
	run_id?: string | null;
	server_label?: string | null;
	server_name?: string | null;
	tools?: MCPListToolsTool[];
	error?: MCPToolError | null;
	status?: MCPToolCallStatus | null;
};

export type ReasoningStepSummaryPartChunk = {
	reasoning_step_id: number;
	part_index: number;
	summary_text: string;
	summary_part_id: number;
};

export type ReasoningCall = {
	id: string;
	index: number;
	output_index?: number;
	type: 'reasoning';
	summary: ReasoningStepSummaryPartChunk[] | null;
	run_id: string | null;
	status: 'in_progress' | 'completed' | 'incomplete';
};

// TODO(jnu): support function calling, updates for v2
export type ToolCallDelta =
	| CodeInterpreterCall
	| FileSearchCall
	| WebSearchCall
	| McpCall
	| McpListToolsCall;

export type ThreadStreamToolCallCreatedChunk = {
	type: 'tool_call_created';
	tool_call: ToolCallDelta;
};

export type ThreadStreamToolCallDeltaChunk = {
	type: 'tool_call_delta';
	delta: ToolCallDelta;
};

export type ThreadStreamReasoningStepCreatedChunk = {
	type: 'reasoning_step_created';
	reasoning_step: ReasoningCall;
};

export type ThreadStreamReasoningSummaryPartAddedChunk = {
	type: 'reasoning_step_summary_part_added';
	summary_part: ReasoningStepSummaryPartChunk;
};

export type ThreadStreamReasoningSummaryDeltaChunk = {
	type: 'reasoning_summary_text_delta';
	reasoning_step_id: number;
	summary_part_id: number;
	delta: string;
};

export type ThreadStreamReasoningStepCompletedChunk = {
	type: 'reasoning_step_completed';
	reasoning_step_id: number;
	status: 'in_progress' | 'completed' | 'incomplete';
	thought_for?: string | null;
};

export type ThreadStreamErrorChunk = {
	type: 'error';
	detail: string;
};

export type ThreadPreSendErrorChunk = {
	type: 'presend_error';
	detail: string;
};

export type ThreadServerErrorChunk = {
	type: 'server_error';
	detail: string;
};

export type ThreadRunActiveErrorChunk = {
	type: 'run_active_error';
	detail: string;
};

export type ThreadStreamDoneChunk = {
	type: 'done';
};

export type ThreadHTTPErrorChunk = {
	detail: string;
};

export type ThreadValidationError = {
	detail: {
		loc: string[];
		msg: string;
		type: string;
	}[];
};

export type ThreadStreamChunk =
	| ThreadStreamMessageDeltaChunk
	| ThreadStreamMessageCreatedChunk
	| ThreadStreamErrorChunk
	| ThreadRunActiveErrorChunk
	| ThreadPreSendErrorChunk
	| ThreadServerErrorChunk
	| ThreadStreamDoneChunk
	| ThreadStreamToolCallCreatedChunk
	| MessageContentCodeOutputImageURL
	| MessageContentCodeOutputLogs
	| ThreadStreamToolCallDeltaChunk
	| ThreadStreamReasoningStepCreatedChunk
	| ThreadStreamReasoningSummaryPartAddedChunk
	| ThreadStreamReasoningSummaryDeltaChunk
	| ThreadStreamReasoningStepCompletedChunk;

/**
 * Stream chunks from a thread.
 */
const streamThreadChunks = (res: Response) => {
	if (!res.body) {
		throw new Error('No response body');
	}
	const stream = res.body
		.pipeThrough(new TextDecoderStream())
		.pipeThrough(new TextLineStream())
		.pipeThrough(new JSONStream());
	const reader = stream.getReader();
	if (res.status === 422) {
		return {
			stream,
			reader,
			async *[Symbol.asyncIterator]() {
				const error = await reader.read();
				const error_ = error.value as ThreadValidationError;
				const message = error_.detail
					.map((error) => {
						const location = error.loc.join(' -> ');
						return `Error at ${location}: ${error.msg}`;
					})
					.join('\n');
				yield {
					type: 'presend_error',
					detail: `We were unable to send your message, because it was not accepted by our server: ${message}`
				} as ThreadPreSendErrorChunk;
			}
		};
	} else if (res.status === 409) {
		return {
			stream,
			reader,
			async *[Symbol.asyncIterator]() {
				const error = await reader.read();
				const error_ = error.value as ThreadHTTPErrorChunk;
				yield {
					type: 'run_active_error',
					detail: `We were unable to send your message: ${error_.detail}`
				} as ThreadRunActiveErrorChunk;
			}
		};
	} else if (res.status !== 200) {
		return {
			stream,
			reader,
			async *[Symbol.asyncIterator]() {
				const error = await reader.read();
				const error_ = error.value as ThreadHTTPErrorChunk;
				yield {
					type: 'presend_error',
					detail: `We were unable to send your message: ${error_.detail}`
				} as ThreadPreSendErrorChunk;
			}
		};
	}
	return {
		stream,
		reader,
		async *[Symbol.asyncIterator]() {
			let chunk = await reader.read();
			while (!chunk.done) {
				yield chunk.value as ThreadStreamChunk;
				chunk = await reader.read();
			}
		}
	};
};

/**
 * Post a new message to the thread.
 */
export const postMessage = async (
	f: Fetcher,
	classId: number,
	threadId: number,
	data: NewThreadMessageRequest
) => {
	const url = `class/${classId}/thread/${threadId}`;
	const res = await _fetch(
		f,
		'POST',
		url,
		{ 'Content-Type': 'application/json' },
		JSON.stringify(data)
	);
	return streamThreadChunks(res);
};

/**
 * Parameters for getting a thread run.
 */
export type CreateThreadRunParams = {
	timezone?: string;
};
/**
 * Create a new thread run.
 */
export const createThreadRun = async (
	f: Fetcher,
	classId: number,
	threadId: number,
	data: CreateThreadRunParams
) => {
	const url = `class/${classId}/thread/${threadId}/run`;
	const res = await _fetch(
		f,
		'POST',
		url,
		{ 'Content-Type': 'application/json' },
		JSON.stringify(data)
	);
	return streamThreadChunks(res);
};

/**
 * Query parameters for getting the last run of a thread.
 */
export type GetLastRunParams = {
	block?: boolean;
};

/**
 * Get the last run of a thread.
 */
export const getLastThreadRun = async (
	f: Fetcher,
	classId: number,
	threadId: number,
	block: boolean = true
) => {
	const url = `class/${classId}/thread/${threadId}/last_run`;
	return await GET<GetLastRunParams, ThreadRun>(f, url, { block });
};

/**
 * Information about getting help with the app.
 */
export type SupportInfo = {
	blurb: string;
	can_post: boolean;
};

/**
 * Get information about support.
 */
export const getSupportInfo = async (f: Fetcher) => {
	const url = `support`;
	return await GET<never, SupportInfo>(f, url);
};

/**
 * Parameters for creating a support request.
 */
export type SupportRequest = {
	email?: string;
	name?: string;
	category?: string;
	message: string;
};

/**
 * Create a new support request.
 */
export const postSupportRequest = async (f: Fetcher, data: SupportRequest) => {
	const url = `support`;
	return await POST<SupportRequest, GenericStatus>(f, url, data);
};

/**
 * OpenAI generation states.
 */
const TERMINAL_STATES = new Set(['expired', 'completed', 'incomplete', 'failed', 'cancelled']);

/**
 * Check if a run is in a terminal state.
 */
export const finished = (run: OpenAIRun | null | undefined) => {
	if (!run) {
		return false;
	}

	return TERMINAL_STATES.has(run.status);
};

/**
 * Request for logging in via magic link sent to email.
 */
export type MagicLoginRequest = {
	email: string;
	forward: string;
};

/**
 * Perform a login sending a magic link.
 */
export const loginWithMagicLink = async (f: Fetcher, email: string, forward: string) => {
	const url = `login/magic`;
	const response = await POST<MagicLoginRequest, GenericStatus>(f, url, {
		email,
		forward
	});
	if (response.$status === 403 && response.detail?.startsWith('/')) {
		if (browser) {
			// Force the browser to request the SSO page to trigger a chain of redirects
			// for the authentication flow.
			window.location.href = response.detail;
			return { $status: 303, detail: "Redirecting to your organization's login page ..." };
		}
	}
	return response;
};

export type LMSPlatform = 'canvas';

export type LTIStatus = 'pending' | 'linked' | 'error';

export type LTIClass = {
	id: number;
	registration_id: number;
	lti_status: LTIStatus;
	lti_platform: LMSPlatform;
	course_name: string | null;
	course_term: string | null;
	course_id: string;
	canvas_account_name?: string | null;
	client_id?: string | null;
};

export type LTIClasses = {
	classes: LTIClass[];
};

export const loadLTIClasses = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/lti/classes`;
	return await GET<never, LTIClasses>(f, url);
};

export type LMSType = 'canvas';

export type LMSInstance = {
	tenant: string;
	tenant_friendly_name: string;
	type: LMSType;
	base_url: string;
};

export type LMSInstances = {
	instances: LMSInstance[];
};
export const loadLMSInstances = async (f: Fetcher, classId: number, lms_type: LMSType) => {
	const url = `class/${classId}/lms/${lms_type}`;
	return await GET<never, LMSInstances>(f, url);
};

export type CanvasRedirect = {
	url: string;
};

/**
 * Request for state token for Canvas sync.
 */
export const getCanvasLink = async (f: Fetcher, classId: number, tenant: string) => {
	const url = `class/${classId}/lms/canvas/${tenant}/link`;
	return await GET<never, CanvasRedirect>(f, url);
};

/**
 * Dismiss Canvas Sync box.
 */
export const dismissCanvasSync = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/lms/canvas/sync/dismiss`;
	return await POST<never, GenericStatus>(f, url);
};

/**
 * Bring back Canvas Sync box.
 */
export const bringBackCanvasSync = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/lms/canvas/sync/enable`;
	return await POST<never, GenericStatus>(f, url);
};

export type LMSClasses = {
	classes: LMSClass[];
};

export type LMSClass = {
	lms_id: number;
	name: string | null;
	course_code: string | null;
	term: string | null;
	lms_tenant: string;
};

export const loadCanvasClasses = async (f: Fetcher, classId: number, tenant: string) => {
	const url = `class/${classId}/lms/canvas/${tenant}/classes`;
	return await GET<never, LMSClasses>(f, url);
};

export const saveCanvasClass = async (
	f: Fetcher,
	classId: number,
	tenant: string,
	canvasClassId: string
) => {
	const url = `class/${classId}/lms/canvas/${tenant}/classes/${canvasClassId}`;
	return await POST<never, GenericStatus>(f, url);
};

export const verifyCanvasClass = async (
	f: Fetcher,
	classId: number,
	tenant: string,
	canvasClassId: string
) => {
	const url = `class/${classId}/lms/canvas/${tenant}/classes/${canvasClassId}/verify`;
	return await POST<never, GenericStatus>(f, url);
};

export const syncCanvasClass = async (f: Fetcher, classId: number, tenant: string) => {
	const url = `class/${classId}/lms/canvas/${tenant}/sync`;
	return await POST<never, GenericStatus>(f, url);
};

export const deleteCanvasClassSync = async (
	f: Fetcher,
	classId: number,
	tenant: string,
	keep: boolean
) => {
	const url = `class/${classId}/lms/canvas/${tenant}/sync`;
	return await DELETE<{ keep_users: boolean }, GenericStatus>(f, url, { keep_users: keep });
};

export const removeCanvasConnection = async (
	f: Fetcher,
	classId: number,
	tenant: string,
	keep: boolean
) => {
	const url = `class/${classId}/lms/canvas/${tenant}/account`;
	return await DELETE<{ keep_users: boolean }, GenericStatus>(f, url, { keep_users: keep });
};

/**
 * Roles for users in a class.
 */
export const ROLES = ['admin', 'teacher', 'student'] as const;

/**
 * List of available roles. These map to the API.
 */
export type Role = (typeof ROLES)[number];

/**
 * List of available roles. These map to the API.
 */
export const ROLE_LABELS: Record<Role, string> = {
	admin: 'Administrator',
	teacher: 'Moderator',
	student: 'Member'
};

/**
 * List of available roles. Adds explanation for admin.
 */
export const ROLE_LABELS_INHERIT_ADMIN: Record<Role, string> = {
	admin: 'Administrator (Inherited)',
	teacher: 'Moderator',
	student: 'Member'
};

/**
 * Information about file types and support.
 */
export type FileTypeInfo = {
	name: string;
	mime_type: string;
	file_search: boolean;
	code_interpreter: boolean;
	vision: boolean;
	extensions: string[];
};

/**
 * Lookup function for file types.
 */
export type MimeTypeLookupFn = (t: string) => FileTypeInfo | undefined;

/**
 * Information about upload support.
 */
export type UploadInfo = {
	types: FileTypeInfo[];
	allow_private: boolean;
	private_file_max_size: number;
	class_file_max_size: number;
};

type FileContentTypeAcceptFilters = {
	file_search: boolean;
	code_interpreter: boolean;
	vision: boolean;
};

/**
 * Generate the string used for the "accept" attribute in file inputs.
 */
const _getAcceptString = (
	types: FileTypeInfo[],
	filters: Partial<FileContentTypeAcceptFilters> = {}
) => {
	return types
		.filter((ft) => {
			// If file_search is enabled, we can return everything that supports file_search.
			// If code_interpreter is enabled, we can also return everything that supports code_interpreter.
			return (
				(filters.file_search && ft.file_search) ||
				(filters.code_interpreter && ft.code_interpreter) ||
				(filters.vision && ft.vision)
			);
		})
		.map((ft) => ft.mime_type)
		.join(',');
};

/**
 * Function to filter files based on their content type.
 */
export type FileSupportFilter = (file: ServerFile) => boolean;

/**
 * Function to get a filter for files based on their content type.
 */
export type GetFileSupportFilter = (
	filters: Partial<FileContentTypeAcceptFilters>
) => FileSupportFilter;

/**
 * Get information about uploading files.
 */
export const getClassUploadInfo = async (f: Fetcher, classId: number) => {
	const url = `class/${classId}/upload_info`;
	const infoResponse = expandResponse(await GET<never, UploadInfo>(f, url));

	const info = infoResponse.data || {
		types: [],
		allow_private: false,
		private_file_max_size: 0,
		class_file_max_size: 0,
		error: infoResponse.error
	};

	// Create a lookup table for mime types.
	const _mimeTypeLookup = new Map<string, FileTypeInfo>();
	info.types.forEach((ft) => {
		_mimeTypeLookup.set(ft.mime_type.toLowerCase(), ft);
	});

	// Lookup function for mime types
	const mimeType = (mime: string) => {
		const slug = mime.toLowerCase().split(';')[0].trim();
		return _mimeTypeLookup.get(slug);
	};

	return {
		...info,
		/**
		 * Lookup information about supported mimetypes.
		 */
		mimeType,
		/**
		 * Get accept string based on capabilities.
		 */
		fileTypes(filters: Partial<FileContentTypeAcceptFilters> = {}) {
			return _getAcceptString(info.types, filters);
		},
		/**
		 * Get accept string for the given assistants based on their capabilities.
		 */
		fileTypesForAssistants(...assistants: Assistant[]) {
			const capabilities = new Set<string>();
			for (const a of assistants) {
				const tools = (a.tools ? JSON.parse(a.tools) : []) as Tool[];
				for (const t of tools) {
					capabilities.add(t.type);
				}
			}

			const filters = {
				file_search: capabilities.has('file_search'),
				code_interpreter: capabilities.has('code_interpreter')
			};

			return _getAcceptString(info.types, filters);
		},
		/**
		 * Get a filter function for file support based on capabilities.
		 */
		getFileSupportFilter(filters: Partial<FileContentTypeAcceptFilters> = {}) {
			return (file: ServerFile) => {
				const support = mimeType(file.content_type);
				if (!support) {
					return false;
				}
				return (
					(!!filters.file_search && support.file_search) ||
					(!!filters.code_interpreter && support.code_interpreter) ||
					(!!filters.vision && support.vision)
				);
			};
		}
	};
};

/**
 * Self-reported information that the user can send us.
 */
export type ExtraUserInfo = {
	first_name?: string;
	last_name?: string;
	display_name?: string;
};

/**
 * Update self-reported information about the user.
 */
export const updateUserInfo = async (f: Fetcher, data: ExtraUserInfo) => {
	const url = `me`;
	return await PUT<ExtraUserInfo, AppUser>(f, url, data);
};

/**
 * Information about a user agreement.
 */

export type AgreementBody = {
	id: number;
	body: string;
};

export type Agreement = {
	id: number;
	name: string;
	created: string;
	updated: string | null;
};

export type Agreements = {
	agreements: Agreement[];
};

export type AgreementPolicyLite = {
	id: number;
};

export type AgreementDetail = {
	id: number;
	name: string;
	body: string;
	policies: AgreementPolicyLite[];
};

export type AgreementLite = {
	id: number;
	name: string;
};

export type AgreementPolicy = {
	id: number;
	name: string;
	agreement_id: number;
	agreement: AgreementLite;
	not_before: string | null;
	not_after: string | null;
	apply_to_all: boolean;
};

export type ExternalLoginProviderLite = {
	id: number;
};

export type AgreementPolicyDetail = {
	id: number;
	name: string;
	agreement_id: number;
	not_before: string;
	not_after: string;
	apply_to_all: boolean;
	limit_to_providers: ExternalLoginProviderLite[];
};

export type AgreementPolicies = {
	policies: AgreementPolicy[];
};

export type CreateAgreementRequest = {
	name: string;
	body: string;
};

export type UpdateAgreementRequest = {
	name?: string;
	body?: string;
};

export type CreateAgreementPolicyRequest = {
	name: string;
	agreement_id: number;
	apply_to_all: boolean;
	limit_to_providers: number[] | null;
};

export type UpdateAgreementPolicyRequest = {
	name?: string;
	agreement_id?: number;
	apply_to_all?: boolean;
	limit_to_providers?: number[] | null;
};

export const getAgreementByPolicyId = async (f: Fetcher, policy_id: number) => {
	const url = `me/terms/${policy_id}`;
	return await GET<never, AgreementBody>(f, url);
};

export const acceptAgreementByPolicyId = async (f: Fetcher, policy_id: number) => {
	const url = `me/terms/${policy_id}`;
	return await POST<never, GenericStatus>(f, url);
};

export const listAgreements = async (f: Fetcher) => {
	const url = `admin/terms/agreement`;
	return await GET<never, Agreements>(f, url);
};

export const createAgreement = async (f: Fetcher, data: CreateAgreementRequest) => {
	const url = `admin/terms/agreement`;
	return await POST<CreateAgreementRequest, GenericStatus>(f, url, data);
};

export const getAgreement = async (f: Fetcher, agreement_id: number) => {
	const url = `admin/terms/agreement/${agreement_id}`;
	return await GET<never, AgreementDetail>(f, url);
};

export const updateAgreement = async (
	f: Fetcher,
	agreement_id: number,
	data: UpdateAgreementRequest
) => {
	const url = `admin/terms/agreement/${agreement_id}`;
	return await PUT<UpdateAgreementRequest, GenericStatus>(f, url, data);
};

export const listAgreementPolicies = async (f: Fetcher) => {
	const url = `admin/terms/policy`;
	return await GET<never, AgreementPolicies>(f, url);
};

export const createAgreementPolicy = async (f: Fetcher, data: CreateAgreementPolicyRequest) => {
	const url = `admin/terms/policy`;
	return await POST<CreateAgreementPolicyRequest, AgreementPolicyDetail>(f, url, data);
};

export const getAgreementPolicy = async (f: Fetcher, policy_id: number) => {
	const url = `admin/terms/policy/${policy_id}`;
	return await GET<never, AgreementPolicyDetail>(f, url);
};

export const updateAgreementPolicy = async (
	f: Fetcher,
	policy_id: number,
	data: UpdateAgreementPolicyRequest
) => {
	const url = `admin/terms/policy/${policy_id}`;
	return await PUT<UpdateAgreementPolicyRequest, GenericStatus>(f, url, data);
};

export type ToggleAgreementPolicyRequest = {
	action: 'enable' | 'disable';
};

export const toggleAgreementPolicy = async (
	f: Fetcher,
	policy_id: number,
	data: ToggleAgreementPolicyRequest
) => {
	const url = `admin/terms/policy/${policy_id}/status`;
	return await PATCH<ToggleAgreementPolicyRequest, GenericStatus>(f, url, data);
};

export const createAudioWebsocket = (classId: number, threadId: number): WebSocket => {
	if (!browser) {
		throw new Error('WebSocket can only be created in a browser environment.');
	}
	const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
	const host = window.location.host;
	const params = new URLSearchParams();
	const anonymousSessionToken = getAnonymousSessionToken();
	if (anonymousSessionToken) {
		params.set('session_token', anonymousSessionToken);
	}
	const anonymousShareToken = getAnonymousShareToken();
	if (anonymousShareToken) {
		params.set('share_token', anonymousShareToken);
	}
	// If we're in an LTI context, include the session token as a query param
	// (WebSockets can't use Authorization headers)
	const ltiToken = getLTISessionToken();
	if (ltiToken) {
		params.set('lti_session', ltiToken);
	}
	const url = `${protocol}://${host}/api/v1/class/${classId}/thread/${threadId}/audio?${params}`;
	return new WebSocket(url);
};

export type StatusComponentUpdate = {
	incidentId: string;
	incidentName: string;
	incidentStatus: string;
	updateStatus: string;
	body: string;
	updatedAt: string | null;
	shortlink: string | null;
	impact: string | null;
};

export const STATUS_COMPONENT_IDS = {
	classic: '2f2dmn0q4ntj',
	nextGen: 'glp8y01h0srn'
};

export const STATUS_COMPONENT_GROUP_ID = 'vp0p38k9dwqd';
