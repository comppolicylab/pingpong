import * as api from '$lib/api';
import { error } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';

/**
 * Load data needed for class layout.
 */
export const load: LayoutLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);

  const [
    classDataResponse,
    classes,
    assistantsResponse,
    filesResponse,
    uploadInfoResponse,
    threads
  ] = await Promise.all([
    api.getClass(fetch, classId).then(api.expandResponse),
    api
      .getMyClasses(fetch)
      .then(api.explodeResponse)
      .then((c) => c.classes),
    api.getAssistants(fetch, classId).then(api.expandResponse),
    api.getClassFiles(fetch, classId).then(api.expandResponse),
    api.getClassUploadInfo(fetch, classId),
    api.getClassThreads(fetch, classId)
  ]);

  if (classDataResponse.error) {
    error(classDataResponse.$status, classDataResponse.error.detail || 'Unknown error');
  }

  let assistants: api.Assistant[] = [];
  let assistantCreators: api.AssistantCreators = {};
  if (assistantsResponse.data) {
    assistants = assistantsResponse.data.assistants.sort((a, b) => a.name.localeCompare(b.name));
    assistantCreators = assistantsResponse.data.creators;
  }

  return {
    hasAssistants: !!assistants && assistants.length > 0,
    hasBilling: !!classDataResponse.data.api_key,
    class: classDataResponse.data,
    classes,
    assistants,
    assistantCreators,
    files: filesResponse.data?.files || [],
    uploadInfo: uploadInfoResponse,
    threads
  };
};
