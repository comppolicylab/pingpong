import * as api from '$lib/api';

export async function load({ fetch, params }) {
  const data = await api.getThread(fetch, params.classId, params.threadId);
  return {
    thread: data.thread,
    run: data.run,
    messages: data.messages,
    participants: data.participants,
  };
}
