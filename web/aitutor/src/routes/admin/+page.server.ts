import * as api from "$lib/api";
import { forwardRequest } from "$lib/proxy";

export const actions = {
  createInstitution: async (event) => {
    return await forwardRequest(api.createInstitution, event);
  },
};
