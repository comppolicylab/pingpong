import * as api from '$lib/api';
import { forwardRequest } from '$lib/proxy';

export const actions = {
    newMessage: async(event) => {
      return await forwardRequest((f, d) => api.postMessage(f, event.params.classId, event.params.threadId, d), event);
    },
};
