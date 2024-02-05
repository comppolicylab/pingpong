import type { Actions } from './$types';
import { fail } from '@sveltejs/kit';
import * as api from '$lib/api';

export const actions: Actions = {
  /**
   * Send a login link to the user's email.
   */
  loginWithMagicLink: async (event) => {
    const body = await event.request.formData();
    const email = body.get('email') as string | undefined;
    if (!email) {
      return fail(400, { email, success: false, error: 'Missing email' });
    }

    const result = await api.loginWithMagicLink(event.fetch, email);
    if (result.$status < 300) {
      return { email, error: null, success: true };
    } else {
      return fail(result.$status, { email, success: false, error: result.detail });
    }
  }
};
