import {threads} from '$lib/stores/threads';
import type {PageLoad} from "./$types";

export const load: PageLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const threadId = parseInt(params.threadId, 10);
  const thread = threads(fetch, classId, threadId);

  // kick off the thread poller, but don't wait for it
  thread.refresh();
  return {
    thread,
  };
}
