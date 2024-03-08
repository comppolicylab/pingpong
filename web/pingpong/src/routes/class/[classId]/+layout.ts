import * as api from '$lib/api';
import type { ErrorResponse } from '$lib/api';
import { error } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';

/**
 * Load data needed for class layout.
 */
export const load: LayoutLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);

  const [classData, { creators: assistantCreators, assistants }, { files }, uploadInfo] =
    await Promise.all([
      api.getClass(fetch, classId),
      api.getAssistants(fetch, classId),
      api.getClassFiles(fetch, classId),
      api.getClassUploadInfo(fetch, classId)
    ]);

  if (classData.$status >= 300) {
    throw error(classData.$status, (classData as ErrorResponse).detail || 'Unknown error');
  }

  return {
    hasAssistants: !!assistants && assistants.length > 0,
    hasBilling: !!classData?.api_key,
    class: classData,
    assistants,
    assistantCreators,
    files,
    uploadInfo
  };
};
