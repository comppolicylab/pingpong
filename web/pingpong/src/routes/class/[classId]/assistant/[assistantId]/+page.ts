import type { PageLoad } from './$types';
import type { Assistant } from '$lib/api';

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ params, fetch, parent }) => {
  const isCreating = params.assistantId === 'new';
  let assistant: Assistant | null = null;
  if (!isCreating) {
    const parentData = await parent();
    assistant =
      parentData.assistants.find((a) => a.id === parseInt(params.assistantId, 10)) || null;
  }

  return {
    isCreating,
    assistantId: isCreating ? null : parseInt(params.assistantId, 10),
    assistant,
    selectedFiles: (assistant?.files || []).map((file) => file.file_id)
  };
};
