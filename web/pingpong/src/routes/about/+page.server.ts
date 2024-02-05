import { fail } from '@sveltejs/kit';
import * as api from '$lib/api';

export const actions = {
  support: async ({ fetch, request }) => {
    const body = await request.formData();

    const message = body.get('message');
    if (!message) {
      return fail(400, { detail: 'Message is required' });
    }

    const data = {
      message,
      email: body.get('email') || undefined,
      name: body.get('name') || undefined,
      category: body.get('category') || undefined
    };

    const result = await api.postSupportRequest(fetch, data);
    if (result.$status < 300) {
      return { success: true };
    } else {
      return fail(result.status);
    }
  }
};
