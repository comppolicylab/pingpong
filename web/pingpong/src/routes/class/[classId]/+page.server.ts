import * as api from '$lib/api';
import { forwardRequest } from '$lib/proxy';
import { fail } from '@sveltejs/kit';
import type { Actions } from './$types';

export const actions: Actions = {
  /**
   * Create a new conversation thread.
   */
  newThread: async (event) => {
    return await forwardRequest((f, d) => {
      const message = d['message'];
      if (!message) {
        throw { $status: 400, detail: 'Message is required' };
      }

      const assistantId = parseInt(d['assistant_id'], 10);

      if (!assistantId) {
        throw { $status: 400, detail: 'Assistant is required' };
      }

      const file_ids = d['file_ids'] ? (d['file_ids'] as string).split(',') : [];

      const classId = parseInt(event.params.classId, 10);
      const parties = d['parties']
        ? (d['parties'] as string).split(',').map((p) => parseInt(p))
        : [];

      return api.createThread(f, classId, {
        message,
        assistant_id: assistantId,
        parties,
        file_ids
      });
    }, event);
  }
};
