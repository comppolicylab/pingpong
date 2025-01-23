import { browser } from '$app/environment';
import { TextLineStream, JSONStream } from '$lib/streams';

/**
 * HTTP methods.
 */
export type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

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
  path = `${path}?${params}`;
  return await _fetchJSON<R>(f, method, path);
};

/**
 * Method that passes data in the body.
 */
const _bmethod = async <T extends BaseData, R extends BaseData>(
  f: Fetcher,
  method: 'POST' | 'PUT',
  path: string,
  data?: T
) => {
  const body = JSON.stringify(data);
  const headers = { 'Content-Type': 'application/json' };
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
 * Information about an institution.
 */
export type Institution = {
  id: number;
  name: string;
  description: string | null;
  logo: string | null;
  created: string;
  updated: string | null;
};

/**
 * Overall status of the session.
 */
export type SessionStatus = 'valid' | 'invalid' | 'missing' | 'error';

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
  class_id: number;
  private: boolean | null;
  uploader_id: number | null;
  created: string;
  updated: string | null;
};

/**
 * List of files.
 */
export type ServerFiles = {
  files: ServerFile[];
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

/**
 * Parameters for a new institution.
 */
export type CreateInstitutionRequest = {
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

/**
 * Get an institution by ID.
 */
export const getInstitution = async (f: Fetcher, id: string) => {
  return await GET<never, Institution>(f, `institution/${id}`);
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
  lms_status: LMSStatus | null;
  lms_class: LMSClass | null;
  lms_last_synced: string | null;
  any_can_create_assistant: boolean | null;
  any_can_publish_assistant: boolean | null;
  any_can_publish_thread: boolean | null;
  any_can_upload_class_file: boolean | null;
  download_link_expiration: string | null;
  last_rate_limited_at: string | null;
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
  any_can_publish_thread?: boolean;
  any_can_upload_class_file?: boolean;
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
 * Delete a new class.
 */
export const deleteClass = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}`;
  return await DELETE<never, GenericStatus>(f, url);
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
  return await GET<never, SummarySubscription>(f, `class/${classId}/summarize/subscription`);
};

/**
 * Subscribe to the class summary.
 */
export const subscribeToSummary = async (f: Fetcher, classId: number) => {
  return await POST<never, GenericStatus>(f, `class/${classId}/summarize/subscription`);
};

/**
 * Unsubscribe from the class summary.
 */
export const unsubscribeFromSummary = async (f: Fetcher, classId: number) => {
  return await DELETE<never, GenericStatus>(f, `class/${classId}/summarize/subscription`);
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
  description: string;
  is_latest: boolean;
  is_new: boolean;
  highlight: boolean;
  supports_vision: boolean;
};

export type AssistantModelOptions = {
  value: string;
  name: string;
  description: string;
  supports_vision: boolean;
  is_new: boolean;
  highlight: boolean;
};

/**
 * List of language models.
 */
export type AssistantModels = {
  models: AssistantModel[];
};

/**
 * Get models available with the api key for the class.
 */
export const getModels = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/models`;
  return await GET<never, AssistantModels>(f, url);
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

/**
 * Information about an assistant.
 */
export type Assistant = {
  id: number;
  name: string;
  description: string | null;
  instructions: string;
  model: string;
  temperature: number;
  tools: string;
  class_id: number;
  creator_id: number;
  published: string | null;
  use_latex: boolean | null;
  hide_prompt: boolean | null;
  locked: boolean | null;
  endorsed: boolean | null;
  created: string;
  updated: string | null;
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
 * OpenAI tool.
 */
export type Tool = {
  type: string;
};

/**
 * Parameters for creating an assistant.
 */
export type CreateAssistantRequest = {
  name: string;
  description: string;
  instructions: string;
  model: string;
  temperature: number;
  tools: Tool[];
  code_interpreter_file_ids: string[];
  file_search_file_ids: string[];
  published?: boolean;
  use_latex?: boolean;
  hide_prompt?: boolean;
  deleted_private_files?: number[];
};

/**
 * Parameters for updating an assistant.
 */
export type UpdateAssistantRequest = {
  name?: string;
  description?: string;
  instructions?: string;
  model?: string;
  temperature?: number;
  tools?: Tool[];
  code_interpreter_file_ids?: string[];
  file_search_file_ids?: string[];
  published?: boolean;
  use_latex?: boolean;
  hide_prompt?: boolean;
  deleted_private_files?: number[];
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
  purpose: FileUploadPurpose = 'assistants'
) => {
  const url = fullPath(`class/${classId}/user/${userId}/file`);
  return _doUpload(url, file, opts, purpose);
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
  purpose: FileUploadPurpose
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
  purpose: FileUploadPurpose = 'assistants'
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
    xhr.setRequestHeader('X-Upload-Purpose', purpose);
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

export type LMSType = 'canvas';

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
 * Remove a user from a class.
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
  message: string;
  tools_available: Tool[];
  file_search_file_ids?: string[];
  code_interpreter_file_ids?: string[];
  vision_file_ids?: string[];
};

/**
 * Thread information.
 */
export type Thread = {
  id: number;
  name: string | null;
  thread_id: string;
  class_id: number;
  assistant_names?: Record<number, string> | null;
  assistant_id: number;
  private: boolean;
  tools_available: string | null;
  user_names?: string[];
  created: string;
  last_activity: string;
};

/**
 * Create a new conversation thread.
 */
export const createThread = async (f: Fetcher, classId: number, data: CreateThreadRequest) => {
  const url = `class/${classId}/thread`;
  return await POST<CreateThreadRequest, Thread>(f, url, data);
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
    | 'expired';
  thread_id: string;
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

export type TextAnnotation = TextAnnotationFilePath | TextAnnotationFileCitation;

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

export type MessageContentCodeOutputImageFile = {
  image_file: ImageFile;
  type: 'code_output_image_file';
};

export type MessageContentCode = {
  code: string;
  type: 'code';
};

export type CodeInterpreterCallPlaceholder = {
  run_id: string;
  step_id: string;
  thread_id: string;
  type: 'code_interpreter_call_placeholder';
};

export type Content =
  | MessageContentImageFile
  | MessageContentText
  | MessageContentCode
  | MessageContentCodeOutputImageFile
  | CodeInterpreterCallPlaceholder;

export type OpenAIMessage = {
  id: string;
  assistant_id: string | null;
  content: Content[];
  created_at: number;
  file_search_file_ids?: string[];
  code_interpreter_file_ids?: string[];
  vision_file_ids?: string[];
  metadata: Record<string, unknown> | null;
  object: 'thread.message' | 'code_interpreter_call_placeholder';
  role: 'user' | 'assistant';
  run_id: string | null;
  thread_id: string;
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
  attachments: Record<string, ServerFile>;
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
  openai_thread_id: string;
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
  openai_thread_id: string,
  run_id: string,
  step_id: string
) => {
  const url = `class/${classId}/thread/${threadId}/ci_messages`;
  const opts = {
    openai_thread_id: openai_thread_id,
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
  limit: number;
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
      ci_messages: [],
      error: expanded.error
    };
  }

  const n = expanded.data.messages.length;
  const lastPage = n < expanded.data.limit;
  return {
    messages: expanded.data.messages,
    ci_messages: expanded.data.ci_messages,
    limit: expanded.data.limit,
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

export type ToolOutput = ToolImageOutput;

export type ToolCallIO = {
  input: string | null;
  outputs: Array<ToolOutput> | null;
};

export type CodeInterpreterCall = {
  code_interpreter: ToolCallIO;
  id: string;
  index: number;
  type: 'code_interpreter';
};

export type FileSearchCall = {
  id: string;
  index: number;
  type: 'file_search';
  file_search: object;
};

// TODO(jnu): support function calling, updates for v2
export type ToolCallDelta = CodeInterpreterCall | FileSearchCall;

export type ThreadStreamToolCallCreatedChunk = {
  type: 'tool_call_created';
  tool_call: ToolCallDelta;
};

export type ThreadStreamToolCallDeltaChunk = {
  type: 'tool_call_delta';
  delta: ToolCallDelta;
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
  | ThreadPreSendErrorChunk
  | ThreadServerErrorChunk
  | ThreadStreamDoneChunk
  | ThreadStreamToolCallCreatedChunk
  | ThreadStreamToolCallDeltaChunk;

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
 * Create a new thread run.
 */
export const createThreadRun = async (f: Fetcher, classId: number, threadId: number) => {
  const url = `class/${classId}/thread/${threadId}/run`;
  const res = await _fetch(f, 'POST', url);
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

export type CanvasRedirect = {
  url: string;
};

/**
 * Request for state token for Canvas sync.
 */
export const getCanvasLink = async (f: Fetcher, classId: number, tenant: string) => {
  const url = `class/${classId}/canvas/${tenant}/link`;
  return await GET<never, CanvasRedirect>(f, url);
};

/**
 * Dismiss Canvas Sync box.
 */
export const dismissCanvasSync = async (f: Fetcher, classId: number, tenant: string) => {
  const url = `class/${classId}/canvas/${tenant}/sync/dismiss`;
  return await POST<never, GenericStatus>(f, url);
};

/**
 * Bring back Canvas Sync box.
 */
export const bringBackCanvasSync = async (f: Fetcher, classId: number, tenant: string) => {
  const url = `class/${classId}/canvas/${tenant}/sync/enable`;
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
};

export const loadCanvasClasses = async (f: Fetcher, classId: number, tenant: string) => {
  const url = `class/${classId}/canvas/${tenant}/classes`;
  return await GET<never, LMSClasses>(f, url);
};

export const saveCanvasClass = async (
  f: Fetcher,
  classId: number,
  tenant: string,
  canvasClassId: string
) => {
  const url = `class/${classId}/canvas/${tenant}/classes/${canvasClassId}`;
  return await POST<never, GenericStatus>(f, url);
};

export const verifyCanvasClass = async (
  f: Fetcher,
  classId: number,
  tenant: string,
  canvasClassId: string
) => {
  const url = `class/${classId}/canvas/${tenant}/classes/${canvasClassId}/verify`;
  return await POST<never, GenericStatus>(f, url);
};

export const syncCanvasClass = async (f: Fetcher, classId: number, tenant: string) => {
  const url = `class/${classId}/canvas/${tenant}/sync`;
  return await POST<never, GenericStatus>(f, url);
};

export const deleteCanvasClassSync = async (
  f: Fetcher,
  classId: number,
  tenant: string,
  keep: boolean
) => {
  const url = `class/${classId}/canvas/${tenant}/sync`;
  return await DELETE<{ keep_users: boolean }, GenericStatus>(f, url, { keep_users: keep });
};

export const removeCanvasConnection = async (
  f: Fetcher,
  classId: number,
  tenant: string,
  keep: boolean
) => {
  const url = `class/${classId}/canvas/${tenant}/account`;
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
