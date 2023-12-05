import * as api from '$lib/api';

export async function load({ fetch, params }) {
  const thread = await api.getThread(fetch, params.classId, params.threadId);
  return {
    thread,
  };
}
