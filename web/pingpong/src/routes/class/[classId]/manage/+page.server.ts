import * as api from '$lib/api';
import {forwardRequest} from '$lib/proxy';
import {fail, redirect} from "@sveltejs/kit";
import {invalid} from "$lib/validate";
import type {Actions} from "./$types";

export const actions: Actions = {

  /**
   * Create a user-class association.
   */
  createUser: async (event) => {
    return await forwardRequest((f, d) => {
      const classId = parseInt(event.params.classId, 10);
      const email = d.email;
      if (!email) {
        throw invalid("email", "Email is required");
      }

      const role = d.role;
      if (!role) {
        throw invalid("role", "Role is required");
      }

      const title = d.title;
      if (!title) {
        throw invalid("title", "Title is required");
      }

      return api.createClassUser(f, classId, {email, role, title});
    }, event);
  },

  /**
   * Bulk add users to a class.
   */
  createUsers: async (event) => {
    const body = await event.request.formData();
    const emails = (body.get('emails') as string) || '';
    // Split emails by newlines or commas.
    const emailList = emails.split(/[\n,]+/).map(e => e.trim()).filter(e => e.length > 0);

    if (emailList.length === 0) {
      return invalid("emails", "Emails are required");
    }

    const role = body.get('role') as string | undefined;
    if (!role) {
      return invalid("role", "Role is required");
    }

    const title = body.get('title') as string | undefined;
    if (!title) {
      return invalid("title", "Title is required");
    }

    const data: api.CreateClassUsersRequest = {
      roles: emailList.map(e => ({
        email: e,
        role,
        title,
      })),
    };

    const classId = parseInt(event.params.classId, 10);
    return await api.createClassUsers(event.fetch, classId, data);
  },

  /**
   * Update a user in a class.
   */
  updateUser: async (event) => {
    return await forwardRequest((f, d) => {
      // User ID is in the URL, not the body.
      const userId = parseInt(d.user_id);

      if (!userId) {
        throw invalid("user_id", "User ID is required");
      }

      const role = d.role;
      if (!role) {
        throw invalid("role", "Role is required");
      }

      const title = d.title;
      if (!title) {
        throw invalid("title", "Title is required");
      }

      const classId = parseInt(event.params.classId, 10);
      return api.updateClassUser(f, classId, userId, {role, title});
    }, event);
  },

  /**
   * Update the class metadata
   */
  updateClass: async (event) => {
    return await forwardRequest((f, d) => {
      const classId = parseInt(event.params.classId, 10);

      if (!d.name) {
        throw invalid("name", "Name is required");
      }

      if (!d.term) {
        throw invalid("term", "Term is required");
      }

      return api.updateClass(f, classId, d);
    }, event, {checkboxes: ['any_can_create_assistant', 'any_can_publish_assistant']});
  },

  /**
   * Create a new class assistant.
   */
  createAssistant: async (event) => {
    const body = await event.request.formData();

    const rawTools = (body.get('tools') as string | undefined) || '';
    const tools: api.Tool[] = [{"type": "retrieval"}];
    if (rawTools) {
      for (const tool of rawTools.split(",")) {
        tools.push({type: tool});
      }
    }

    const file_ids = body.getAll('files') as string[];

    const name = body.get('name') as string | undefined;
    if (!name) {
      return invalid("name", "Name is required");
    }

    const description = (body.get('description') as string | undefined) || '';

    const instructions = body.get('instructions') as string | undefined
    if (!instructions) {
      return invalid("instructions", "Instructions are required");
    }

    const model = body.get('model') as string | undefined;
    if (!model) {
      return invalid("model", "Model is required");
    }


    const data: api.CreateAssistantRequest = {
      name,
      description,
      instructions,
      model,
      tools,
      file_ids,
      published: body.get('published') === "on",
      use_latex: body.get('use_latex') === "on",
      hide_prompt: body.get('hide_prompt') === "on",
    };

    const classId = parseInt(event.params.classId, 10);
    const resp = await api.createAssistant(event.fetch, classId, data);
    if (resp.$status >= 400) {
      return fail(resp.$status, resp);
    }

    return resp;
  },

  /**
   * Update a class assistant.
   */
  updateAssistant: async (event) => {
    const body = await event.request.formData();

    const tools: api.Tool[] = [{"type": "retrieval"}];
    const rawTools = (body.get('tools') as string | undefined) || '';
    if (rawTools) {
      for (const tool of rawTools.split(",")) {
        tools.push({type: tool});
      }
    }
    const file_ids = body.getAll('files') as string[];

    const name = body.get('name') as string | undefined;
    if (!name) {
      return invalid("name", "Name is required");
    }

    const description = (body.get('description') as string | undefined) || '';

    const instructions = body.get('instructions') as string | undefined
    if (!instructions) {
      return invalid("instructions", "Instructions are required");
    }

    const model = body.get('model') as string | undefined;
    if (!model) {
      return invalid("model", "Model is required");
    }

    const data: api.UpdateAssistantRequest = {
      name,
      description,
      instructions,
      model,
      tools,
      file_ids,
      published: body.get('published') === "on",
      use_latex: body.get('use_latex') === "on",
      hide_prompt: body.get('hide_prompt') === "on",
    };

    const classId = parseInt(event.params.classId, 10);
    const assistantId = parseInt((body.get("assistantId") as string) || '0', 10);
    if (!assistantId) {
      return invalid("assistantId", "Assistant ID is required");
    }

    const response = await api.updateAssistant(event.fetch, classId, assistantId, data);
    throw redirect(307, `${event.url.pathname}?save`);
  },

  /**
   * Update the API key for a class.
   */
  updateApiKey: async (event) => {
    const body = await event.request.formData();
    const apiKey = (body.get('apiKey') as string | undefined) || '';
    const classId = parseInt(event.params.classId, 10);

    return await api.updateApiKey(event.fetch, classId, apiKey);
  },

  /**
   * Upload a file.
   */
  uploadFile: async (event) => {
    const body = await event.request.formData();
    const file = body.get('file') as File | undefined;
    if (!file?.name || !file?.size) {
      return invalid("file", "File is required");
    }

    const classId = parseInt(event.params.classId, 10);
    return await api.uploadFile(event.fetch, classId, file);
  },

  /**
   * Delete a file.
   */
  deleteFile: async (event) => {
    const body = await event.request.formData();
    const classId = parseInt(event.params.classId, 10);
    const fileId = parseInt((body.get("fileId") as string) || '0', 10);
    if (!fileId) {
      throw invalid("fileId", "File ID is required");
    }
    const resp = await api.deleteFile(event.fetch, classId, fileId);
    if (resp.$status >= 400) {
      return fail(resp.$status, resp);
    }
    return resp;
  },

};
