import * as api from "$lib/api";
import { forwardRequest } from "$lib/proxy";

export const actions = {
  createClass: async (event) => {
    const instId = event.params.institutionId;
    return await forwardRequest(
      (f, d) => api.createClass(f, instId, d), event);
  },
};
