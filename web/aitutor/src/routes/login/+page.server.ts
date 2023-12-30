import { fail } from "@sveltejs/kit";
import * as api from "$lib/api";

export const actions = {

  loginWithMagicLink: async (event) => {
    const body = await event.request.formData();
    const email = body.get("email");
    const result = await api.loginWithMagicLink(event.fetch, email);
    if (result.$status < 300) {
      return {email, error: null, success: true};
    } else {
      return fail(result.$status, {email, success: false, error: result.detail});
    }
  },

};
