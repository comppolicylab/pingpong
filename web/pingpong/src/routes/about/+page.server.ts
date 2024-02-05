import { fail } from '@sveltejs/kit';
import * as api from '$lib/api';

export const actions = {
  support: async ({ fetch, request }) => {
    const body = await request.formData();

    const message = body.get('message') as string | undefined;
    if (!message) {
      return fail(400, { detail: 'Message is required' });
    }

    const data = {
      message: message,
      email: body.get('email') as string | undefined,
      name: body.get('name') as string | undefined,
      category: body.get('category') as string | undefined
    };

    const result = await api.postSupportRequest(fetch, data);
    if (result.$status < 300) {
      return { success: true };
    } else {
      return fail(result.$status);
    }
  }
};
