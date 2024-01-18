/**
 * HTTP methods.
 */
export type Method = "GET" | "POST" | "PUT" | "DELETE";

/**
 * General fetcher type.
 */
export type Fetcher = (input: RequestInfo, init?: RequestInit) => Promise<Response>;

/**
 * Base data type for all API responses.
 */
export type BaseData = Record<string, any>;

/**
 * Common fetch method.
 */
const _fetch = async (f: Fetcher, method: Method, path: string, headers?: Record<string, string>, body?: string | FormData) => {
    path = path.replace(/^\/+/, "");
    const fullPath = `/api/v1/${path}`;
    const res = await f(fullPath, {
      method,
      headers,
      body,
      credentials: "include",
      mode: "cors",
    });

    let data: {} = {};

    try {
      data = await res.json();
    } catch (e) {
      // Do nothing
    }

    return {"$status": res.status, ...data};
}

/**
 * Method that passes data in the query string.
 */
const _qmethod = async <T extends BaseData>(f: Fetcher, method: "GET" | "DELETE", path: string, data?: T) => {
  const params = new URLSearchParams(data as Record<string, string>);
  path = `${path}?${params}`;
  return await _fetch(f, method, path);
}

/**
 * Method that passes data in the body.
 */
const _bmethod = async <T extends BaseData>(f: Fetcher, method: "POST" | "PUT", path: string, data?: T) => {
  const body = JSON.stringify(data);
  const headers = {"Content-Type": "application/json"};
  return await _fetch(f, method, path, headers, body);
}

/**
 * Query with GET.
 */
const GET = async <T extends BaseData>(f: Fetcher, path: string, data?: T) => {
  return await _qmethod(f, "GET", path, data);
}

/**
 * Query with DELETE.
 */
const DELETE = async <T extends BaseData>(f: Fetcher, path: string, data?: T) => {
  return await _qmethod(f, "DELETE", path, data);
}

/**
 * Query with POST.
 */
const POST = async <T extends BaseData>(f: Fetcher, path: string, data?: T) => {
  return await _bmethod(f, "POST", path, data);
}

/**
 * Query with PUT.
 */
const PUT = async <T extends BaseData>(f: Fetcher, path: string, data?: T) => {
  return await _bmethod(f, "PUT", path, data);
}

/**
 * Get the current user.
 */
export const me = async (f: Fetcher) => {
  return await GET(f, "me");
}

/**
 * Parameters for a new institution.
 */
export type CreateInstitutionRequest = {
  name: string;
}

/**
 * Create a new institution.
 */
export const createInstitution = async (f: Fetcher, data: CreateInstitutionRequest) => {
  return await POST(f, "institution", data);
}

/**
 * Get all institutions.
 */
export const getInstitutions = async (f: Fetcher) => {
  return await GET(f, "institutions");
}

/**
 * Get an institution by ID.
 */
export const getInstitution = async (f: Fetcher, id: string) => {
  return await GET(f, `institution/${id}`);
}

/**
 * Get all the classes at an institution.
 */
export const getClasses = async (f: Fetcher, id: string) => {
  return await GET(f, `institution/${id}/classes`);
}

/**
 * Get classes visible to the current user.
 */
export const getMyClasses = async (f: Fetcher) => {
  return await GET(f, `classes`);
}

/**
 * Parameters for creating a new class.
 */
export type CreateClassRequest = {
  name: string;
  term: string;
}

/**
 * Parameters for updating a class.
 */
export type UpdateClassRequest = {
  name?: string;
  term?: string;
  any_can_create_assistant?: string;
  any_can_update_assistant?: string;
}

/**
 * Create a new class.
 */
export const createClass = async (f: Fetcher, instId: number, data: CreateClassRequest) => {
  const url = `institution/${instId}/class`;
  return await POST(f, url, data);
}

/**
 * Parameters for updating a class.
 */
export const updateClass = async (f: Fetcher, classId: number, data: UpdateClassRequest) => {
  const url = `class/${classId}`;
  return await PUT(f, url, data);
}

/**
 * Update the API key for a class.
 */
export const updateApiKey = async (f: Fetcher, classId: number, apiKey: string) => {
  const url = `class/${classId}/api_key`;
  return await PUT(f, url, {api_key: apiKey});
}

/**
 * Fetch the API key for a class.
 */
export const getApiKey = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/api_key`;
  return await GET(f, url);
}

/**
 * Fetch a class by ID.
 */
export const getClass = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}`;
  return await GET(f, url);
}

/**
 * Fetch all files for a class.
 */
export const getClassFiles = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/files`;
  return await GET(f, url);
}

/**
 * Fetch all (visible) threads for a class.
 */
export const getClassThreads = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/threads`;
  return await GET(f, url);
}

/**
 * Fetch all assistants for a class.
 */
export const getAssistants = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/assistants`;
  return await GET(f, url);
}

/**
 * OpenAI tool.
 */
export type Tool = {
  type: string;
}

/**
 * Parameters for creating an assistant.
 */
export type CreateAssistantRequest = {
  name: string;
  instructions: string;
  model: string;
  tools: Tool[];
  file_ids: string[];
  published?: boolean;
}

/**
 * Parameters for updating an assistant.
 */
export type UpdateAssistantRequest = {
  name?: string;
  instructions?: string;
  model?: string;
  tools?: Tool[];
  file_ids?: string[];
  published?: boolean;
}

/**
 * Create a new assistant.
 */
export const createAssistant = async (f: Fetcher, classId: number, data: CreateAssistantRequest) => {
  const url = `class/${classId}/assistant`;
  return await POST(f, url, data);
}

/**
 * Update an existing assistant.
 */
export const updateAssistant = async (f: Fetcher, classId: number, assistantId: number, data: UpdateAssistantRequest) => {
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
 * Upload a file to a class.
 */
export const uploadFile = async (f: Fetcher, classId: number, file: File) => {
  const url = `class/${classId}/file`;
  const formData = new FormData();
  formData.append("upload", file);
  return await _fetch(f, "POST", url, {}, formData);
}

/**
 * Fetch users in a class.
 */
export const getClassUsers = async (f: Fetcher, classId: number) => {
  const url = `class/${classId}/users`;
  return await GET(f, url);
}

/**
 * Parameters for creating a new class user.
 */
export type CreateClassUserRequest = {
  email: string;
  role: string;
  title: string;
}

/**
 * Create a new class user.
 */
export const createClassUser = async (f: Fetcher, classId: number, data: CreateClassUserRequest) => {
  return createClassUsers(f, classId, {roles: [data]});
}

/**
 * Plural version of CreateClassUserRequest.
 */
export type CreateClassUsersRequest = {
  roles: CreateClassUserRequest[];
}

/**
 * Create multiple class users.
 */
export const createClassUsers = async (f: Fetcher, classId: number, data: CreateClassUsersRequest) => {
  const url = `class/${classId}/user`;
  return await POST(f, url, data);
}

/**
 * Parameters for updating a class user.
 */
export type UpdateClassUserRequest = {
  role: string;
  title: string;
}

/**
 * Update a class user.
 */
export const updateClassUser = async (f: Fetcher, classId: number, userId: number, data: UpdateClassUserRequest) => {
  const url = `class/${classId}/user/${userId}`;
  return await PUT(f, url, data);
}

/**
 * Parameters for creating a new thread.
 */
export type CreateThreadRequest = {
  message: string;
  assistant_id: number;
  parties?: number[];
};

/**
 * Create a new conversation thread.
 */
export const createThread = async (f: Fetcher, classId: number, data: CreateThreadRequest) => {
  const url = `class/${classId}/thread`;
  return await POST(f, url, data);
}

/**
 * Get a thread by ID.
 */
export const getThread = async (f: Fetcher, classId: number, threadId: number) => {
  const url = `class/${classId}/thread/${threadId}`;
  return await GET(f, url);
}

/**
 * Post a new message to the thread.
 */
export const postMessage = async (f: Fetcher, classId: number, threadId: number, data: {}) => {
  const url = `class/${classId}/thread/${threadId}`;
  return await POST(f, url, data);
}

/**
 * Get the last run of a thread.
 */
export const getLastThreadRun = async (f: Fetcher, classId: number, threadId: number, block: boolean = true) => {
  const url = `class/${classId}/thread/${threadId}/last_run`;
  return await GET(f, url, {block});
}

/**
 * OpenAI generation states.
 */
const TERMINAL_STATES = new Set(["expired", "completed", "failed", "cancelled"]);

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
  return await POST(f, url, {email});
}

/**
 * List of available language models.
 */
export const languageModels = [
    // "gpt-4-vision-preview",
    "gpt-4-1106-preview",
];

/**
 * List of available roles. These map to the API.
 */
export const ROLES = new Map([
  ["admin", "Admin"],
  ["write", "Write"],
  ["read", "Read"],
  ]);

/**
 * Titles for users. These are arbitary.
 */
export const TITLES = [
  "Owner",
  "Admin",
  "Professor",
  "Course Assistant",
  "Student",
];
