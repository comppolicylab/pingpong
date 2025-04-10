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
  let threadModel = '';
  let threadTools = '';
  let threadInteractionMode: 'chat' | 'voice' | null = null;
  let assistantGrants = { canViewAssistant: false };
  if (!expanded.error) {
    threadTools = expanded.data.tools_available || '';
    threadModel = expanded.data.model || '';
    threadInteractionMode = expanded.data.thread.interaction_mode || 'chat';
    if (expanded.data.thread.assistant_id) {
      assistantGrants = await api.grants(fetch, {
        canViewAssistant: {
          target_type: 'assistant',
          target_id: expanded.data.thread.assistant_id,
          relation: 'can_view'
        }
      });
    }
  }

  return {
    threadData,
    threadModel,
    threadInteractionMode,
    availableTools: threadTools,
    canDeleteThread: threadGrants.canDelete,
    canPublishThread: threadGrants.canPublish,
    canViewAssistant: assistantGrants.canViewAssistant
  };
};
