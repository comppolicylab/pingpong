import * as api from '$lib/api';
import {forwardRequest} from '$lib/proxy';

export const actions = {

  createAssistant: async (event) => {
    const body = await event.request.formData();

    const rawTools = body.get('tools');
    const tools: api.Tool[] = [{"type": "retrieval"}];
    if (rawTools) {
      for (const tool of rawTools.split(",")) {
        tools.push({type: tool});
      }
    }

    const data: api.CreateAssistantRequest = {
      name: body.get('name'),
      instructions: body.get('instructions'),
      model: body.get('model'),
      tools,
      file_ids: body.get('files').split(","),
    };

    return await api.createAssistant(event.fetch, event.params.classId, data);
  },

  uploadFile: async (event) => {
    const body = await event.request.formData();
    const file = body.get('file');
    return await api.uploadFile(event.fetch, event.params.classId, file);
  },

};
