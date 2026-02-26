import * as api from '$lib/api';
import { redirect } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';

/**
 * Load additional data needed for managing the class.
 */
export const load: LayoutLoad = async ({ fetch, params, parent }) => {
	const { class: classData } = await parent();
	if (!classData) {
		throw redirect(302, '/');
	}

	const classId = parseInt(params.classId, 10);
	const [grants, editable, institutionGrants] = await Promise.all([
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
			canShareAssistants: {
				target_type: 'class',
				target_id: classId,
				relation: 'can_share_assistants'
			},
			canUploadClassFiles: {
				target_type: 'class',
				target_id: classId,
				relation: 'can_upload_class_files'
			},
			isSupervisor: {
				target_type: 'class',
				target_id: classId,
				relation: 'supervisor'
			}
		}),
		api.grantsList(fetch, 'can_edit', 'assistant'),
		classData.institution_id
			? api.grants(fetch, {
					isInstitutionAdmin: {
						target_type: 'institution',
						target_id: classData.institution_id,
						relation: 'admin'
					}
				})
			: Promise.resolve({ isInstitutionAdmin: false })
	]);

	return {
		grants,
		class: classData,
		editableAssistants: new Set(editable),
		isInstitutionAdmin: institutionGrants.isInstitutionAdmin
	};
};
