import * as api from '$lib/api';
import type { PageLoad } from './$types';

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const [grants, modelsResponse] = await Promise.all([
    api.grants(fetch, {
      canEditInfo: { target_type: 'class', target_id: classId, relation: 'can_edit_info' },
      canCreateAssistants: {
        target_type: 'class',
        target_id: classId,
        relation: 'can_create_assistants'
      },
      canPublishAssistants: {
        target_type: 'class',
        target_id: classId,
        relation: 'can_publish_assistants'
      },
      canPublishThreads: {
        target_type: 'class',
        target_id: classId,
        relation: 'can_publish_threads'
      },
      canUploadClassFiles: {
        target_type: 'class',
        target_id: classId,
        relation: 'can_upload_class_files'
      },
      isAdmin: {
        target_type: 'class',
        target_id: classId,
        relation: 'admin'
      },
      canViewApiKey: { target_type: 'class', target_id: classId, relation: 'can_view_api_key' },
      canViewUsers: { target_type: 'class', target_id: classId, relation: 'can_view_users' },
      canDelete: { target_type: 'class', target_id: classId, relation: 'can_delete' },
      canManageUsers: { target_type: 'class', target_id: classId, relation: 'can_manage_users' }
    }),
    api.getModels(fetch, classId).then(api.expandResponse)
  ]);

  let api_key = '';
  if (grants.canViewApiKey) {
    const apiKeyResponse = api.expandResponse(await api.getApiKey(fetch, classId));
    if (apiKeyResponse.error) {
      api_key = '[error fetching API key!]';
    } else {
      api_key = apiKeyResponse.data.api_key;
    }
  }

  const models = modelsResponse.error ? [] : modelsResponse.data.models;

  return {
    models,
    apiKey: api_key || '',
    grants
  };
};
