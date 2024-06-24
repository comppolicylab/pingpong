import * as api from '$lib/api';
import type { LayoutLoad } from './$types';

/**
 * Load additional data needed for managing the class.
 */
export const load: LayoutLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const [grants, editable] = await Promise.all([
    api.grants(fetch, {
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
      canUploadClassFiles: {
        target_type: 'class',
        target_id: classId,
        relation: 'can_upload_class_files'
      }
    }),
    api.grantsList(fetch, 'can_edit', 'assistant')
  ]);

  return {
    grants,
    editableAssistants: new Set(editable)
  };
};
