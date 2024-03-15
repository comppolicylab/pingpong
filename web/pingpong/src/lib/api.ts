import { browser } from '$app/environment';

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

/**
 * Error response. The $status will be >= 400.
 */
export type ErrorResponse = Error & BaseResponse;

/**
 * Check whether a response is an error.
 */
export const isErrorResponse = (r: unknown): r is ErrorResponse => {
  return !!r && Object.hasOwn(r, '$status') && (r as BaseResponse).$status >= 400;
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
): Promise<R & BaseResponse> => {
  const res = await _fetch(f, method, path, headers, body);

  let data: BaseData = {};

  try {
    data = await res.json();
  } catch (e) {
    // Do nothing
  }

  return { $status: res.status, ...data } as R & BaseResponse;
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
  const params = new URLSearchParams(data as Record<string, string>);
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
};

/**
 * List of user roles in a class.
 */
export type UserClassRoles = {
  roles: UserClassRole[];
  silent: boolean;
};

/**
 * User information.
 */
export type AppUser = {
  id: number;
  name: string | null;
  email: string;
  state: UserState;
  classes: UserClassRole[];
  institutions: Institution[];
  created: string;
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
  const verdicts: NamedGrants = {};
  for (let i = 0; i < grantNames.length; i++) {
    verdicts[grantNames[i]] = results.grants[i].verdict;
  }
  return verdicts as { [name in keyof T]: boolean };
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
  api_key: string | null;
  any_can_create_assistant: boolean | null;
  any_can_publish_assistant: boolean | null;
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
 * Parameters for creating a new class.
 */
export type CreateClassRequest = {
  name: string;
  term: string;
  any_can_create_assistant?: boolean;
  any_can_publish_assistant?: boolean;
};

/**
 * Parameters for updating a class.
 */
export type UpdateClassRequest = {
  name?: string;
  term?: string;
  any_can_create_assistant?: boolean;
  any_can_publish_assistant?: boolean;
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
 * Api key from the server.
 */
export type ApiKey = {
  api_key: string;
};

/**
 * Update the API key for a class.
 */
export const updateApiKey = async (f: Fetcher, classId: number, apiKey: string) => {
  const url = `class/${classId}/api_key`;
  return await PUT<ApiKey, ApiKey>(f, url, { api_key: apiKey });
};

/**
 * Fetch the API key for a class.
 */
export const getApiKey = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/api_key`;
  return await GET<never, ApiKey>(f, url);
};

/**
 * Language model information.
 */
export type AssistantModel = {
  id: string;
  created: string;
  owner: string;
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
export type GetClassThreadsOpts = {
  limit?: number;
  before?: string;
};

/**
 * Fetch all (visible) threads for a class.
 */
export const getClassThreads = async (f: Fetcher, classId: number, opts?: GetClassThreadsOpts) => {
  const url = `class/${classId}/threads`;
  const result = await GET<GetClassThreadsOpts, Threads>(f, url, opts);
  let lastPage = false;
  // Add a flag to indicate if this is the last page of results.
  // If there was a requested limit and the server returned
  // fewer results, then we know we're on the last page.
  // If there was no limit, then the last page is when we get
  // an empty list of threads.
  if (result.threads) {
    if (opts?.limit) {
      lastPage = result.threads.length < opts.limit;
    } else {
      lastPage = result.threads.length === 0;
    }
  }
  return {
    ...result,
    lastPage
  };
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
  tools: string;
  class_id: number;
  creator_id: number;
  files: ServerFile[];
  published: string | null;
  use_latex: boolean | null;
  hide_prompt: boolean | null;
  created: string;
  updated: string | null;
};

/**
 * Information about multiple assistants, plus metadata about creators.
 */
export type Assistants = {
  assistants: Assistant[];
  creators: { [id: number]: Profile };
};

/**
 * Fetch all assistants for a class.
 */
export const getAssistants = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/assistants`;
  return await GET<never, Assistants>(f, url);
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
  tools: Tool[];
  file_ids: string[];
  published?: boolean;
  use_latex?: boolean;
  hide_prompt?: boolean;
};

/**
 * Parameters for updating an assistant.
 */
export type UpdateAssistantRequest = {
  name?: string;
  description?: string;
  instructions?: string;
  model?: string;
  tools?: Tool[];
  file_ids?: string[];
  published?: boolean;
  use_latex?: boolean;
  hide_prompt?: boolean;
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
  opts?: UploadOptions
) => {
  const url = fullPath(`class/${classId}/user/${userId}/file`);
  return _doUpload(url, file, opts);
};

/**
 * File upload error.
 */
export interface FileUploadFailure {
  error: string;
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
export type FileUploader = (file: File, progress: (p: number) => void) => FileUploadInfo;

/**
 * Wrapper function to call the file deleter more easily.
 *
 * Does not need to be used, but helpful for the UI.
 */
export type FileRemover = (fileId: number) => Promise<void>;

/**
 * Upload a file to the given endpoint.
 */
const _doUpload = (url: string, file: File, opts?: UploadOptions): FileUploadInfo => {
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
    xhr.upload.onprogress = onProgress;
    xhr.onreadystatechange = () => {
      if (xhr.readyState === 4) {
        if (xhr.status < 300) {
          info.state = 'success';
          info.response = JSON.parse(xhr.responseText) as ServerFile;
          resolve(info.response);
        } else {
          info.state = 'error';
          info.response = { error: xhr.responseText };
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
  email: string;
  roles: ClassUserRoles;
  state: UserState;
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
  const lastPage = response.users.length < response.limit;

  return {
    ...response,
    lastPage
  };
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
  roles: ClassUserRoles;
};

/**
 * Create a new class user.
 */
export const createClassUser = async (
  f: Fetcher,
  classId: number,
  data: CreateClassUserRequest
) => {
  return createClassUsers(f, classId, { roles: [data] });
};

/**
 * Plural version of CreateClassUserRequest.
 */
export type CreateClassUsersRequest = {
  roles: CreateClassUserRequest[];
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
  return await POST<CreateClassUsersRequest, UserClassRoles>(f, url, data);
};

/**
 * Parameters for updating a class user.
 */
export type UpdateClassUserRequest = {
  role: string;
  verdict: boolean;
};

/**
 * Update a class user.
 */
export const updateClassUser = async (
  f: Fetcher,
  classId: number,
  userId: number,
  data: UpdateClassUserRequest
) => {
  const url = `class/${classId}/user/${userId}`;
  return await PUT<UpdateClassUserRequest, UserClassRole>(f, url, data);
};

/**
 * Remove a user from a class.
 */
export const removeClassUser = async (f: Fetcher, classId: number, userId: number) => {
  const url = `class/${classId}/user/${userId}`;
  return await DELETE<never, GenericStatus>(f, url);
};

/**
 * Parameters for creating a new thread.
 */
export type CreateThreadRequest = {
  message: string;
  assistant_id: number;
  parties?: number[];
  file_ids?: string[];
};

/**
 * Simplified user object.
 */
export type UserPlaceholder = {
  id: number;
  email: string;
};

/**
 * Thread information.
 */
export type Thread = {
  id: number;
  name: string;
  thread_id: string;
  class_id: number;
  assistant_id: number;
  private: boolean;
  users: UserPlaceholder[];
  created: string;
  updated: string;
};

/**
 * Create a new conversation thread.
 */
export const createThread = async (f: Fetcher, classId: number, data: CreateThreadRequest) => {
  const url = `class/${classId}/thread`;
  return await POST<CreateThreadRequest, Thread>(f, url, data);
};

type LastError = {
  code: 'server_error' | 'rate_limit_exceeded';
  message: string;
};

type RequiredAction = {
  submit_tool_outputs: unknown;
  type: 'submit_tool_outputs';
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
  expires_at: number;
  failed_at: number | null;
  file_ids: string[];
  instruction: string;
  last_error: LastError | null;
  metadata: Record<string, unknown>;
  model: string;
  object: 'thread.run';
  required_action: RequiredAction | null;
  started_at: number | null;
  status:
    | 'queued'
    | 'in_progress'
    | 'requires_action'
    | 'cancelling'
    | 'cancelled'
    | 'failed'
    | 'completed'
    | 'expired';
  thread_id: string;
  tools: unknown[];
  usage: unknown | null;
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

export type Content = MessageContentImageFile | MessageContentText;

export type OpenAIMessage = {
  id: string;
  assistant_id: string | null;
  content: Content[];
  created_at: number;
  file_ids: string[];
  metadata: Record<string, unknown> | null;
  object: 'thread.message';
  role: 'user' | 'assistant';
  run_id: string | null;
  thread_id: string;
};

/**
 * Accounting of individuals in a thread.
 */
export type ThreadParticipants = {
  user: { [id: number]: Profile };
  assistant: { [id: number]: string };
};

/**
 * Thread object with additional metadata.
 */
export type ThreadWithMeta = {
  thread: Thread;
  hash: string;
  run: OpenAIRun | null;
  messages: OpenAIMessage[];
  participants: ThreadParticipants;
};

/**
 * Get a thread by ID.
 */
export const getThread = async (f: Fetcher, classId: number, threadId: number) => {
  const url = `class/${classId}/thread/${threadId}`;
  return await GET<never, ThreadWithMeta>(f, url);
};

/**
 * Data for posting a new message to a thread.
 */
export type NewThreadMessageRequest = {
  message: string;
  file_ids?: string[];
};

/**
 * Thread with run information.
 */
export type ThreadRun = {
  thread: Thread;
  run: OpenAIRun;
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
  const res = await _fetch(f, 'POST', url, { 'Content-Type': 'application/json' }, JSON.stringify(data));
  if (!res.body) {
    throw new Error('No response body');
  }
  const stream = res.body.pipeThrough(new TextDecoderStream());
  const reader = stream.getReader();
  return {
    stream,
    reader,
    async* [Symbol.asyncIterator]() {
      let chunk = await reader.read();
      while (!chunk.done) {
        yield chunk.value;
        chunk = await reader.read();
      }
    }
  }
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
const TERMINAL_STATES = new Set(['expired', 'completed', 'failed', 'cancelled']);

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
};

/**
 * Perform a login sending a magic link.
 */
export const loginWithMagicLink = async (f: Fetcher, email: string) => {
  const url = `login/magic`;
  return await POST<MagicLoginRequest, GenericStatus>(f, url, { email });
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
  teacher: 'Instructor',
  student: 'Student'
};

/**
 * Information about file types and support.
 */
export type FileTypeInfo = {
  name: string;
  mime_type: string;
  retrieval: boolean;
  code_interpreter: boolean;
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
  retrieval: boolean;
  code_interpreter: boolean;
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
      // If retrieval is enabled, we can return everything that supports retrieval.
      // If code_interpreter is enabled, we can also return everything that supports code_interpreter.
      return (
        (filters.retrieval && ft.retrieval) || (filters.code_interpreter && ft.code_interpreter)
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
  const info = await GET<never, UploadInfo>(f, url);

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
        retrieval: capabilities.has('retrieval'),
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
          (!!filters.retrieval && support.retrieval) ||
          (!!filters.code_interpreter && support.code_interpreter)
        );
      };
    }
  };
};
