import {threads} from '$lib/stores/threads';

export async function load({ fetch, params }) {
  const thread = threads(fetch, params.classId, params.threadId);
  // kick off the thread poller, but don't wait for it
  thread.refresh();
  return {
    thread,
  };
}
