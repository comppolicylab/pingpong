import * as api from '$lib/api';
import {handler} from '$lib/proxy';
import {fail, redirect} from "@sveltejs/kit";
import {invalid} from "$lib/validate";
import type {Actions} from "./$types";

export const actions: Actions = {

  /**
   * Create a user-class association.
   */
  createUser: handler((f, d, event) => {
      const classId = parseInt(event.params.classId, 10);
      return api.createClassUser(f, classId, {email: d.email, role: d.role, title: d.title});
    }),

  /**
   * Bulk add users to a class.
   */
  createUsers: handler((f, d, event) => {
      const emails = (d.emails as string) || '';
      // Split emails by newlines or commas.
      const emailList = emails.split(/[\n,]+/).map(e => e.trim()).filter(e => e.length > 0);

      if (emailList.length === 0) {
        throw invalid("emails", "Emails are required");
      }

      const role = d.role as string | undefined;
      if (!role) {
        throw invalid("role", "Role is required");
      }

      const title = d.title as string | undefined;
      if (!title) {
        throw invalid("title", "Title is required");
      }

      const data: api.CreateClassUsersRequest = {
        roles: emailList.map(e => ({
          email: e,
          role,
          title,
        })),
      };

      const classId = parseInt(event.params.classId, 10);
      return api.createClassUsers(f, classId, data);
    }),

  /**
   * Update a user in a class.
   */
  updateUser: handler((f, d, event) => {
      // User ID is in the URL, not the body.
      const userId = parseInt(d.user_id);

      if (!userId) {
        throw invalid("user_id", "User ID is required");
      }

      const classId = parseInt(event.params.classId, 10);
      return api.updateClassUser(f, classId, userId, {role: d.role, title: d.title});
    }),

  /**
   * Update the class metadata
   */
  updateClass: handler((f, d, event) => {
      const classId = parseInt(event.params.classId, 10);
      return api.updateClass(f, classId, d);
    }, {checkboxes: ['any_can_create_assistant', 'any_can_publish_assistant']}),

  /**
   * Create a new class assistant.
   */
  createAssistant: handler((f, d, event) => {
    const rawTools = (d.tools as string | undefined) || '';
    const tools: api.Tool[] = [{"type": "retrieval"}];
    if (rawTools) {
      for (const tool of rawTools.split(",")) {
        tools.push({type: tool});
      }
    }

    const data: api.CreateAssistantRequest = {
      name: d.name,
      description: d.description,
      instructions: d.instructions,
      model: d.model,
      tools,
      file_ids: d.files as string[],
      published: d.published as boolean,
      use_latex: d.use_latex as boolean,
      hide_prompt: d.hide_prompt as boolean,
    };

    const classId = parseInt(event.params.classId, 10);
    return api.createAssistant(f, classId, data);
  }, {checkboxes: ['published', 'use_latex', 'hide_prompt']}),

  /**
   * Update a class assistant.
   */
  updateAssistant: handler((f, d, event) => {
    const tools: api.Tool[] = [{"type": "retrieval"}];
    const rawTools = (d.tools as string | undefined) || '';
    if (rawTools) {
      for (const tool of rawTools.split(",")) {
        tools.push({type: tool});
      }
    }

    const data: api.UpdateAssistantRequest = {
      name: d.name,
      description: d.description,
      instructions: d.instructions,
      model: d.model,
      tools,
      file_ids: d.files as string[],
      published: d.published as boolean,
      use_latex: d.use_latex as boolean,
      hide_prompt: d.hide_prompt as boolean,
    };

    const classId = parseInt(event.params.classId, 10);
    const assistantId = parseInt((d.assistantId as string) || '0', 10);
    if (!assistantId) {
      throw invalid("assistantId", "Assistant ID is required");
    }

    return api.updateAssistant(event.fetch, classId, assistantId, data);
  }, {checkboxes: ['published', 'use_latex', 'hide_prompt']}),

  /**
   * Update the API key for a class.
   */
  updateApiKey: handler((f, d, event) => {
    const apiKey = (d.apiKey as string | undefined) || '';
    const classId = parseInt(event.params.classId, 10);

    return api.updateApiKey(f, classId, apiKey);
  }),

  /**
   * Upload a file.
   */
  uploadFile: handler((f, d, event) => {
    const file = d.file as File | undefined;
    if (!file?.name || !file?.size) {
      throw invalid("file", "File is required");
    }

    const classId = parseInt(event.params.classId, 10);
    return api.uploadFile(f, classId, file);
  }),

  /**
   * Delete a file.
   */
  deleteFile: handler((f, d, event) => {
    const classId = parseInt(event.params.classId, 10);
    const fileId = parseInt((d.fileId as string) || '0', 10);
    if (!fileId) {
      throw invalid("fileId", "File ID is required");
    }
    return api.deleteFile(f, classId, fileId);
  }),

};
