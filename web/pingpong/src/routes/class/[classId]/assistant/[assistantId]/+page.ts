import type { PageLoad } from './$types';

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ params, fetch }) => {
  const isCreating = params.assistantId === 'new';
  return {
    isCreating,
    assistantId: isCreating ? null : parseInt(params.assistantId, 10)
  };
};
