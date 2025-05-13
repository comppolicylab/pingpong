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
    assistantsResponse,
    filesResponse,
    uploadInfoResponse,
    grants,
    teachersResponse,
    hasAPIKeyResponse
  ] = await Promise.all([
    api.getClass(fetch, classId).then(api.expandResponse),
    api.getAssistants(fetch, classId).then(api.expandResponse),
    api.getClassFiles(fetch, classId).then(api.expandResponse),
    api.getClassUploadInfo(fetch, classId),
    api.grants(fetch, {
      canManage: { target_type: 'class', target_id: classId, relation: 'supervisor' },
      isSupervisor: {
        target_type: 'class',
        target_id: classId,
        relation: 'supervisor'
      }
    }),
    api.getSupervisors(fetch, classId).then(api.expandResponse),
    api.hasAPIKey(fetch, classId).then(api.expandResponse)
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

  const supervisors = teachersResponse.error ? [] : teachersResponse.data.users;

  const hasAPIKey = hasAPIKeyResponse.error ? false : hasAPIKeyResponse.data.has_api_key;

  return {
    hasAssistants: !!assistants && assistants.length > 0,
    class: classDataResponse.data,
    assistants,
    assistantCreators,
    files: filesResponse.data?.files || [],
    uploadInfo: uploadInfoResponse,
    canManage: grants.canManage,
    isSupervisor: grants.isSupervisor,
    hasAPIKey,
    supervisors
  };
};
