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
};

/**
 * Generic response returned by some API endpoints.
 */
export type GenericStatus = {
  status: string;
};

/**
 * Get full API route.
 */
const _fullPath = (path: string) => {
  path = path.replace(/^\/+/, '');
  return `/api/v1/${path}`;
};

/**
 * Common fetch method.
 */
const _fetch = async <R extends BaseData>(
  f: Fetcher,
  method: Method,
  path: string,
  headers?: Record<string, string>,
  body?: string | FormData
): Promise<R & BaseResponse> => {
  const fullPath = _fullPath(path);
  const res = await f(fullPath, {
    method,
    headers,
    body,
    credentials: 'include',
    mode: 'cors'
  });

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
  return await _fetch<R>(f, method, path);
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
  return await _fetch<R>(f, method, path, headers, body);
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
 * Get the current user.
 */
export const me = async (f: Fetcher) => {
  return await GET(f, 'me');
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
 * Get all institutions.
 */
export const getInstitutions = async (f: Fetcher) => {
  return await GET<{}, Institutions>(f, 'institutions');
};

/**
 * Get an institution by ID.
 */
export const getInstitution = async (f: Fetcher, id: string) => {
  return await GET<{}, Institution>(f, `institution/${id}`);
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
  any_can_update_assistant: boolean | null;
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
  return await GET<{}, Classes>(f, `institution/${id}/classes`);
};

/**
 * Get classes visible to the current user.
 */
export const getMyClasses = async (f: Fetcher) => {
  return await GET<{}, Classes>(f, `classes`);
};

/**
 * Parameters for creating a new class.
 */
export type CreateClassRequest = {
  name: string;
  term: string;
};

/**
 * Parameters for updating a class.
 */
export type UpdateClassRequest = {
  name?: string;
  term?: string;
  any_can_create_assistant?: string;
  any_can_update_assistant?: string;
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
 * Update the API key for a class.
 */
export const updateApiKey = async (f: Fetcher, classId: number, apiKey: string) => {
  const url = `class/${classId}/api_key`;
  return await PUT(f, url, { api_key: apiKey });
};

/**
 * Fetch the API key for a class.
 */
export const getApiKey = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/api_key`;
  return await GET(f, url);
};

/**
 * Get models available with the api key for the class.
 */
export const getModels = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/models`;
  return await GET(f, url);
};

/**
 * Fetch a class by ID.
 */
export const getClass = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}`;
  return await GET(f, url);
};

/**
 * Fetch all files for a class.
 */
export const getClassFiles = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/files`;
  return await GET(f, url);
};

/**
 * Fetch all (visible) threads for a class.
 */
export const getClassThreads = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/threads`;
  return await GET(f, url);
};

/**
 * Fetch all assistants for a class.
 */
export const getAssistants = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/assistants`;
  return await GET(f, url);
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
  return await POST(f, url, data);
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
  return await PUT(f, url, data);
};

/**
 * Delete an assistant.
 */
export const deleteAssistant = async (f: Fetcher, classId: number, assistantId: number) => {
  const url = `class/${classId}/assistant/${assistantId}`;
  return await DELETE(f, url);
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
  const url = _fullPath(`class/${classId}/file`);
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
  const url = _fullPath(`class/${classId}/user/${userId}/file`);
  return _doUpload(url, file, opts);
};

/**
 * Server representation of a file.
 */
export interface UploadedFile {
  id: number;
  name: string;
  file_id: string;
  content_type: string;
  class_id: number;
  private: boolean;
  uploader_id: number;
  created: string;
  updated: string | null;
}

/**
 * File upload error.
 */
export interface FileUploadFailure {
  error: string;
}

/**
 * Result of a file upload.
 */
export type FileUploadResult = UploadedFile | FileUploadFailure;

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
          info.response = JSON.parse(xhr.responseText) as UploadedFile;
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
  return await DELETE(f, url);
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
  return await DELETE(f, url);
};

/**
 * Fetch users in a class.
 */
export const getClassUsers = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/users`;
  return await GET(f, url);
};

/**
 * Parameters for creating a new class user.
 */
export type CreateClassUserRequest = {
  email: string;
  role: string;
  title: string;
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
  return await POST(f, url, data);
};

/**
 * Parameters for updating a class user.
 */
export type UpdateClassUserRequest = {
  role: string;
  title: string;
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
  return await PUT(f, url, data);
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
  updated: string | null;
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
 * Email with image.
 */
export type Profile = {
  email: string;
  gravatar_id: string;
  image_url: string;
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
  return await GET<{}, ThreadWithMeta>(f, url);
};

/**
 * Data for posting a new message to a thread.
 */
export type NewThreadMessageRequest = {
  message: string;
  file_ids?: string[];
};

/**
 * Post a new message to the thread.
 */
export const postMessage = async (f: Fetcher, classId: number, threadId: number, data: {}) => {
  const url = `class/${classId}/thread/${threadId}`;
  return await POST(f, url, data);
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
  return await GET(f, url, { block });
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
  return await GET<{}, SupportInfo>(f, url);
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
export const finished = (run: { status: string }) => {
  if (!run) {
    return false;
  }

  return TERMINAL_STATES.has(run.status);
};

/**
 * Perform a login sending a magic link.
 */
export const loginWithMagicLink = async (f: Fetcher, email: string) => {
  const url = `login/magic`;
  return await POST(f, url, { email });
};

/**
 * List of available roles. These map to the API.
 */
export const ROLES = new Map([
  ['admin', 'Admin'],
  ['write', 'Write'],
  ['read', 'Read']
]);

/**
 * Titles for users. These are arbitary.
 */
export const TITLES = ['Owner', 'Admin', 'Professor', 'Course Assistant', 'Student'];

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
 * Information about upload support.
 */
export type UploadInfo = {
  types: FileTypeInfo[];
  allow_private: boolean;
  private_file_max_size: number;
  class_file_max_size: number;
};

/**
 * Generate the string used for the "accept" attribute in file inputs.
 */
const _getAcceptString = (types: FileTypeInfo[]) => {
  return types
    .filter((ft) => ft.retrieval)
    .map((ft) => ft.mime_type)
    .join(',');
};

/**
 * Get information about uploading files.
 */
export const getClassUploadInfo = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/upload_info`;
  const info = await GET<{}, UploadInfo>(f, url);

  // Create a lookup table for mime types.
  const _mimeTypeLookup = new Map<string, FileTypeInfo>();
  info.types.forEach((ft) => {
    _mimeTypeLookup.set(ft.mime_type.toLowerCase(), ft);
  });

  return {
    ...info,
    /**
     * Lookup information about supported mimetypes.
     */
    mimeType: (mime: string) => {
      const slug = mime.toLowerCase().split(';')[0].trim();
      return _mimeTypeLookup.get(slug);
    },
    /**
     * String describing accepted mime types.
     */
    acceptString: _getAcceptString(info.types)
  };
};
