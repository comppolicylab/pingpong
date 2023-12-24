import * as api from '$lib/api';
import {forwardRequest} from '$lib/proxy';
import {redirect} from "@sveltejs/kit";

export const actions = {

  /**
   * Update the class metadata
   */
  updateClass: async (event) => {
    return await forwardRequest((f, d) => api.updateClass(f, event.params.classId, d), event);
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

    const rawFiles = body.get('files');
    const file_ids = rawFiles ? rawFiles.split(",") : [];

    const data: api.CreateAssistantRequest = {
      name: body.get('name'),
      instructions: body.get('instructions'),
      model: body.get('model'),
      tools,
      file_ids,
    };

    return await api.createAssistant(event.fetch, event.params.classId, data);
  },

  /**
   * Update a class assistant.
   */
  updateAssistant: async (event) => {
    const body = await event.request.formData();

    const rawTools = body.get('tools');
    const tools = rawTools ? rawTools.split(",").map(t => ({type: t})) : [];
    const rawFiles = body.get('files');
    const file_ids = rawFiles ? rawFiles.split(",") : [];

    const data: api.UpdateAssistantRequest = {
      name: body.get('name'),
      instructions: body.get('instructions'),
      model: body.get('model'),
      tools,
      file_ids,
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
