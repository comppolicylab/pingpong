import * as api from '$lib/api';
import { error } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';
import { anonymousSessionToken } from '$lib/stores/general';
import { get } from 'svelte/store';

/**
 * Load data needed for class layout.
 */
export const load: LayoutLoad = async ({ fetch, params, parent }) => {
  const classId = parseInt(params.classId, 10);
  const parentData = await parent();

  const shareToken = parentData.shareToken;
  const shareTokenInfo = shareToken ? { share_token: parentData.shareToken } : undefined;
  const anonymousSessionTokenValue = get(anonymousSessionToken);
  console.log('Anonymous session token:', anonymousSessionTokenValue);
  let headers: Record<string, string> = {};
  if (anonymousSessionTokenValue) {
    headers = {
      'X-Anonymous-Thread-Session': anonymousSessionTokenValue
    };
  }
  const [
    classDataResponse,
    assistantsResponse,
    filesResponse,
    uploadInfoResponse,
    grants,
    teachersResponse,
    hasAPIKeyResponse
  ] = await Promise.all([
    api.getClass(fetch, classId, shareTokenInfo).then(api.expandResponse),
    api.getAssistants(fetch, classId, shareTokenInfo).then(api.expandResponse),
    api.getClassFiles(fetch, classId).then(api.expandResponse),
    api.getClassUploadInfo(fetch, classId, shareTokenInfo),
    api.grants(
      fetch,
      {
        canManage: { target_type: 'class', target_id: classId, relation: 'supervisor' },
        isSupervisor: {
          target_type: 'class',
          target_id: classId,
          relation: 'supervisor'
        }
      },
      shareTokenInfo, headers
    ),
    api.getSupervisors(fetch, classId, shareTokenInfo).then(api.expandResponse),
    api.hasAPIKey(fetch, classId, shareTokenInfo).then(api.expandResponse)
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
    supervisors,
    shareTokenInfo
  };
};
