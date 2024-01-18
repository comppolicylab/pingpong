import * as api from '$lib/api';
import {forwardRequest} from '$lib/proxy';
import {redirect} from "@sveltejs/kit";

export const actions = {

  /**
   * Create a user-class association.
   */
  createUser: async (event) => {
    return await forwardRequest((f, d) => api.createClassUser(f, event.params.classId, d), event);
  },

  /**
   * Bulk add users to a class.
   */
  createUsers: async (event) => {
    const body = await event.request.formData();
    const emails = body.get('emails');
    // Split emails by newlines or commas.
    const emailList = emails.split(/[\n,]+/).map(e => e.trim()).filter(e => e.length > 0);

    if (emailList.length === 0) {
      throw new Error("No emails provided");
    }

    const data: api.CreateClassUsersRequest = {
      roles: emailList.map(e => ({
        email: e,
        role: body.get('role'),
        title: body.get('title'),
      })),
    };

    return await api.createClassUsers(event.fetch, event.params.classId, data);
  },

  /**
   * Update a user in a class.
   */
  updateUser: async (event) => {
    return await forwardRequest((f, d) => {
      // User ID is in the URL, not the body.
      const userId = parseInt(d.user_id);
      delete d.user_id;
      // Email can't be updated.
      delete d.email;
      return api.updateClassUser(f, event.params.classId, userId, d);
    }, event);
  },

  /**
   * Update the class metadata
   */
  updateClass: async (event) => {
    return await forwardRequest((f, d) => api.updateClass(f, event.params.classId, d), event, {checkboxes: ['any_can_create_assistant', 'any_can_publish_assistant']});
  },

  /**
   * Create a new class assistant.
   */
  createAssistant: async (event) => {
    const body = await event.request.formData();

    const rawTools = body.get('tools');
    const tools: api.Tool[] = [{"type": "retrieval"}];
    if (rawTools) {
      for (const tool of rawTools.split(",")) {
        tools.push({type: tool});
      }
    }

    const file_ids = body.getAll('files');

    const data: api.CreateAssistantRequest = {
      name: body.get('name'),
      instructions: body.get('instructions'),
      model: body.get('model'),
      tools,
      file_ids,
      published: body.get('published') === "on",
      use_latex: body.get('use_latex') === "on",
    };

    return await api.createAssistant(event.fetch, event.params.classId, data);
  },

  /**
   * Update a class assistant.
   */
  updateAssistant: async (event) => {
    const body = await event.request.formData();

    const tools: api.Tool[] = [{"type": "retrieval"}];
    const rawTools = body.get('tools');
    if (rawTools) {
      for (const tool of rawTools.split(",")) {
        tools.push({type: tool});
      }
    }
    const file_ids = body.getAll('files');

    const data: api.UpdateAssistantRequest = {
      name: body.get('name'),
      instructions: body.get('instructions'),
      model: body.get('model'),
      tools,
      file_ids,
      published: body.get('published') === "on",
      use_latex: body.get('use_latex') === "on",
    };

    const response = await api.updateAssistant(event.fetch, event.params.classId, body.get("assistantId"), data);
    throw redirect(307, `${event.url.pathname}?save`);
  },

  /**
   * Update the API key for a class.
   */
  updateApiKey: async (event) => {
    const body = await event.request.formData();
    const apiKey = body.get('apiKey');
    return await api.updateApiKey(event.fetch, event.params.classId, apiKey);
  },

  /**
   * Upload a file.
   */
  uploadFile: async (event) => {
    const body = await event.request.formData();
    const file = body.get('file');
    return await api.uploadFile(event.fetch, event.params.classId, file);
  },

};
