import * as api from '$lib/api';
import { handler } from '$lib/proxy';
import { invalid } from '$lib/validate';
import type { Actions, RequestEvent } from './$types';

/**
 * Fields for creating a user in the UI.
 */
export type CreateUserForm = {
  email: string;
  role: string;
  title: string;
};

/**
 * Manage multiple users form.
 */
export type CreateUsersForm = {
  emails: string;
  role: string;
  title: string;
};

/**
 * Update user form.
 */
export type UpdateUserForm = {
  user_id: string;
  role: 'admin' | 'teacher' | 'student';
  title?: string;
  verdict: boolean;
};

/**
 * UI for updating a class.
 */
export type UpdateClassForm = {
  name: string;
  term: string;
  any_can_create_assistant: boolean;
  any_can_publish_assistant: boolean;
};

/**
 * Create assistant form.
 */
export type CreateAssistantForm = {
  name: string;
  description: string;
  instructions: string;
  model: string;
  tools: string;
  files: string[];
  published: boolean;
  use_latex: boolean;
  hide_prompt: boolean;
};

/**
 * Update assistant form.
 */
export type UpdateAssistantForm = {
  assistantId: string;
  name: string;
  description: string;
  instructions: string;
  model: string;
  tools: string;
  files: string[];
  published: boolean;
  use_latex: boolean;
  hide_prompt: boolean;
};

/**
 * Update API key form.
 */
export type UpdateApiKeyForm = {
  apiKey: string;
};

export const actions: Actions = {
  /**
   * Create a user-class association.
   */
  createUser: handler<RequestEvent, CreateUserForm>((f, d, event) => {
    const classId = parseInt(event.params.classId, 10);
    return api.createClassUser(f, classId, { email: d.email, role: d.role, title: d.title });
  }),

  /**
   * Bulk add users to a class.
   */
  createUsers: handler<RequestEvent, CreateUsersForm>((f, d, event) => {
    const emails = (d.emails as string) || '';
    // Split emails by newlines or commas.
    const emailList = emails
      .split(/[\n,]+/)
      .map((e) => e.trim())
      .filter((e) => e.length > 0);

    if (emailList.length === 0) {
      throw invalid('emails', 'Emails are required');
    }

    const role = d.role as string | undefined;
    if (!role) {
      throw invalid('role', 'Role is required');
    }

    const title = d.title as string | undefined;
    if (!title) {
      throw invalid('title', 'Title is required');
    }

    const data: api.CreateClassUsersRequest = {
      roles: emailList.map((e) => ({
        email: e,
        role,
        title
      }))
    };

    const classId = parseInt(event.params.classId, 10);
    return api.createClassUsers(f, classId, data);
  }),

  /**
   * Update a user in a class.
   */
  updateUser: handler<RequestEvent, UpdateUserForm>(
    (f, d, event) => {
      // User ID is in the URL, not the body.
      const userId = parseInt(d.user_id);

      if (!userId) {
        throw invalid('user_id', 'User ID is required');
      }

      const classId = parseInt(event.params.classId, 10);
      return api.updateClassUser(f, classId, userId, { role: d.role, verdict: d.verdict });
    },
    { checkboxes: ['verdict'] }
  ),

  /**
   * Remove a user from a class.
   */
  removeUser: handler<RequestEvent, { user_id: string }>((f, d, event) => {
    const userId = parseInt(d.user_id, 10);
    if (!userId) {
      throw invalid('user_id', 'User ID is required');
    }

    const classId = parseInt(event.params.classId, 10);
    return api.removeClassUser(f, classId, userId);
  }),

  /**
   * Update the class metadata
   */
  updateClass: handler<RequestEvent, UpdateClassForm>(
    (f, d, event) => {
      const classId = parseInt(event.params.classId, 10);
      return api.updateClass(f, classId, d);
    },
    { checkboxes: ['any_can_create_assistant', 'any_can_publish_assistant'] }
  ),

  /**
   * Create a new class assistant.
   */
  createAssistant: handler<RequestEvent, CreateAssistantForm>(
    (f, d, event) => {
      const rawTools = (d.tools as string | undefined) || '';
      const tools: api.Tool[] = [{ type: 'retrieval' }];
      if (rawTools) {
        for (const tool of rawTools.split(',')) {
          tools.push({ type: tool });
        }
      }

      const data: api.CreateAssistantRequest = {
        name: d.name,
        description: d.description,
        instructions: d.instructions,
        model: d.model,
        tools,
        file_ids: (d.files || []) as string[],
        published: d.published as boolean,
        use_latex: d.use_latex as boolean,
        hide_prompt: d.hide_prompt as boolean
      };

      const classId = parseInt(event.params.classId, 10);
      return api.createAssistant(f, classId, data);
    },
    { checkboxes: ['published', 'use_latex', 'hide_prompt'], lists: ['files'] }
  ),

  /**
   * Update a class assistant.
   */
  updateAssistant: handler<RequestEvent, UpdateAssistantForm>(
    (f, d, event) => {
      const tools: api.Tool[] = [{ type: 'retrieval' }];
      const rawTools = (d.tools as string | undefined) || '';
      if (rawTools) {
        for (const tool of rawTools.split(',')) {
          tools.push({ type: tool });
        }
      }

      const data: api.UpdateAssistantRequest = {
        name: d.name,
        description: d.description,
        instructions: d.instructions,
        model: d.model,
        tools,
        file_ids: (d.files || []) as string[],
        published: d.published as boolean,
        use_latex: d.use_latex as boolean,
        hide_prompt: d.hide_prompt as boolean
      };

      const classId = parseInt(event.params.classId, 10);
      const assistantId = parseInt((d.assistantId as string) || '0', 10);
      if (!assistantId) {
        throw invalid('assistantId', 'Assistant ID is required');
      }

      return api.updateAssistant(event.fetch, classId, assistantId, data);
    },
    { checkboxes: ['published', 'use_latex', 'hide_prompt'], lists: ['files'] }
  ),

  /**
   * Update the API key for a class.
   */
  updateApiKey: handler<RequestEvent, UpdateApiKeyForm>((f, d, event) => {
    const apiKey = (d.apiKey as string | undefined) || '';
    const classId = parseInt(event.params.classId, 10);

    return api.updateApiKey(f, classId, apiKey);
  })
};
