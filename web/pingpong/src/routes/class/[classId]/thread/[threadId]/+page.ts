import * as api from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const threadId = parseInt(params.threadId, 10);

  const [threadData, threadGrants] = await Promise.all([
    api.getThread(fetch, classId, threadId),
    api.grants(fetch, {
      canDelete: { target_type: 'thread', target_id: threadId, relation: 'can_delete' },
      canPublish: { target_type: 'thread', target_id: threadId, relation: 'can_publish' }
    })
  ]);

  const expanded = api.expandResponse(threadData);
  let threadAvailableTools = '';
  if (!expanded.error) {
    threadAvailableTools = expanded.data.thread.tools_available || '';
  }

  return {
    threadData,
    availableTools: threadAvailableTools,
    canDeleteThread: threadGrants.canDelete,
    canPublishThread: threadGrants.canPublish
  };
};
