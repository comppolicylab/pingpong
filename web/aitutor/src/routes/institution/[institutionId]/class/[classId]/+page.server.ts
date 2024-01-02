import * as api from "$lib/api";
import { forwardRequest } from "$lib/proxy";

export const actions = {
  newThread: async (event) => {
    return await forwardRequest((f, d) => {
      d['assistant_id'] = parseInt(d['assistant_id']);
      d['parties'] = d['parties'] ? d['parties'].split(',').map((p) => parseInt(p)) : [];
      return api.createThread(f, event.params.classId, d);
    }, event);
  }
};
