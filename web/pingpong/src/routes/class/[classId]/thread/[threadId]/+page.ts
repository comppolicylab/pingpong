import { getThread } from '$lib/stores/threads';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const threadId = parseInt(params.threadId, 10);
  const thread = getThread(fetch, classId, threadId);

  return {
    thread
  };
};
