import * as api from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const threadId = parseInt(params.threadId, 10);

  return {
    threadData: api.getThread(fetch, classId, threadId),
  }
}
