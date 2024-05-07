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
};

/**
 * Manage multiple users form.
 */
export type CreateUsersForm = {
  emails: string;
  role: string;
};

/**
 * Update user form.
 */
export type UpdateUserForm = {
  user_id: string;
  role: 'admin' | 'teacher' | 'student';
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
  any_can_publish_thread: boolean;
  any_can_upload_class_file: boolean;
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
    return api.createClassUser(f, classId, {
      email: d.email,
      roles: {
        admin: d.role === 'admin',
        teacher: d.role === 'teacher',
        student: d.role === 'student'
      }
    });
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

    const data: api.CreateClassUsersRequest = {
      roles: emailList.map((e) => ({
        email: e,
        roles: {
          admin: role === 'admin',
          teacher: role === 'teacher',
          student: role === 'student'
        }
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
    {
      checkboxes: [
        'any_can_create_assistant',
        'any_can_publish_assistant',
        'any_can_publish_thread',
        'any_can_upload_class_file'
      ]
    }
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
