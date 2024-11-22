import * as api from '$lib/api';
import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';

/**
 * Load additional data needed for managing the class.
 */
export const load = async ({ fetch, params }: Parameters<PageLoad>[0]) => {
  const classId = parseInt(params.classId, 10);
  const [classDataResponse, grants] = await Promise.all([
    // Even though we `getClass` at the parent layout, we need to do it again here since we might have an updated lastRateLimitedAt value.
    api.getClass(fetch, classId).then(api.expandResponse),
    api.grants(fetch, {
      canEditInfo: { target_type: 'class', target_id: classId, relation: 'can_edit_info' },
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
      isTeacher: {
        target_type: 'class',
        target_id: classId,
        relation: 'teacher'
      },
      isStudent: {
        target_type: 'class',
        target_id: classId,
        relation: 'student'
      },
      canViewApiKey: { target_type: 'class', target_id: classId, relation: 'can_view_api_key' },
      canViewUsers: { target_type: 'class', target_id: classId, relation: 'can_view_users' },
      canDelete: { target_type: 'class', target_id: classId, relation: 'can_delete' },
      canManageUsers: { target_type: 'class', target_id: classId, relation: 'can_manage_users' }
    })
  ]);

  if (classDataResponse.error) {
    error(classDataResponse.$status, classDataResponse.error.detail || 'Unknown error');
  }

  let api_key: api.ApiKey | undefined;
  if (grants.canViewApiKey) {
    const apiKeyResponse = api.expandResponse(await api.getApiKey(fetch, classId));
    if (apiKeyResponse.error) {
      api_key = { api_key: 'error fetching API key!' };
      console.error('Error fetching API key:', apiKeyResponse.error);
    } else {
      api_key = apiKeyResponse.data.api_key;
    }
  }

  return {
    apiKey: api_key,
    grants,
    class: classDataResponse.data
  };
};
