import * as api from "$lib/api";
import { forwardRequest } from "$lib/proxy";

export const actions = {
  newThread: async (event) => {
    return await forwardRequest((f, d) => api.createThread(f, event.params.classId, d), event);
  }
};
