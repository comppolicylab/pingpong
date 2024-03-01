import * as api from '$lib/api';
import type { PageLoad } from './$types';

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const grants = await api.grants(fetch, {
    "canEditInfo": {"target_type": "class", "target_id": classId, "relation": "can_edit_info"},
    "canCreateAssistants": {"target_type": "class", "target_id": classId, "relation": "can_create_assistants"},
    "canPublishAssistants": {"target_type": "class", "target_id": classId, "relation": "can_publish_assistants"},
    "canUploadClassFiles": {"target_type": "class", "target_id": classId, "relation": "can_upload_class_files"},
    "canViewApiKey": {"target_type": "class", "target_id": classId, "relation": "can_view_api_key"},
    "canViewUsers": {"target_type": "class", "target_id": classId, "relation": "can_view_users"},
    "canDelete": {"target_type": "class", "target_id": classId, "relation": "can_delete"},
    "canManageUsers": {"target_type": "class", "target_id": classId, "relation": "can_manage_users"},
  });
  let api_key = '';
  if (grants.canViewApiKey) {
    const apiKeyResponse = await api.getApiKey(fetch, classId);
    api_key = apiKeyResponse.api_key;
  }
  const { users } = await api.getClassUsers(fetch, classId);
  const { models } = await api.getModels(fetch, classId);


  return {
    models,
    apiKey: api_key || '',
    classUsers: users,
    grants,
  };
};
