import * as api from '$lib/api';
import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';

/**
 * Load additional data needed for managing the class.
 */
export const load = async ({ fetch, params }: Parameters<PageLoad>[0]) => {
	const classId = parseInt(params.classId, 10);
	const [classDataResponse, grants, canvasInstances, ltiClasses] = await Promise.all([
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
			canManageUsers: { target_type: 'class', target_id: classId, relation: 'can_manage_users' },
			canReceiveSummaries: {
				target_type: 'class',
				target_id: classId,
				relation: 'can_receive_summaries'
			},
			isRootAdmin: {
				target_type: 'root',
				target_id: 0,
				relation: 'admin'
			}
		}),
		api.loadLMSInstances(fetch, classId, 'canvas').then(api.expandResponse),
		api.loadLTIClasses(fetch, classId).then(api.expandResponse)
	]);

	if (classDataResponse.error) {
		error(classDataResponse.$status, classDataResponse.error.detail || 'Unknown error');
	}

	if (canvasInstances.error) {
		error(canvasInstances.$status, canvasInstances.error.detail || 'Error loading LMS instances');
	}
	if (ltiClasses.error) {
		error(ltiClasses.$status, ltiClasses.error.detail || 'Error loading LTI classes');
	}
	let apiKey: api.ApiKey | undefined;
	let classCredentials: api.ClassCredentialSlot[] | undefined;
	let apiKeyReadError: string | undefined;
	let aiProvider: string | null | undefined = null;
	let hasGeminiCredential: boolean | undefined = false;
	let hasElevenlabsCredential: boolean | undefined = false;
	let defaultKeys: api.DefaultAPIKey[] | undefined;
	if (grants.canViewApiKey || grants.canEditInfo) {
		const apiKeyResponse = await api.getApiKey(fetch, classId).then(api.expandResponse);
		if (apiKeyResponse.error) {
			apiKeyReadError = apiKeyResponse.error.detail || 'Error fetching group credential details.';
			aiProvider = undefined;
			hasGeminiCredential = undefined;
			hasElevenlabsCredential = undefined;
			console.error('Error fetching group credential details.');
		} else {
			apiKey = apiKeyResponse.data.api_key ?? undefined;
			classCredentials = apiKeyResponse.data.credentials ?? undefined;
			aiProvider = apiKeyResponse.data.ai_provider ?? null;
			hasGeminiCredential = apiKeyResponse.data.has_gemini_credential ?? false;
			hasElevenlabsCredential = apiKeyResponse.data.has_elevenlabs_credential ?? false;
		}
	}
	let canReadDefaultApiKeys = false;
	if (grants.canViewApiKey) {
		if (grants.isRootAdmin) {
			canReadDefaultApiKeys = true;
		} else {
			const institutionAdminResponse = classDataResponse.data.institution_id
				? await api.grants(fetch, {
						isInstitutionAdmin: {
							target_type: 'institution',
							target_id: classDataResponse.data.institution_id,
							relation: 'admin'
						}
					})
				: { isInstitutionAdmin: false };
			canReadDefaultApiKeys = institutionAdminResponse.isInstitutionAdmin;
		}
	}
	if (canReadDefaultApiKeys) {
		const defaultKeysResponse = await api.getDefaultAPIKeys(fetch).then(api.expandResponse);
		if (!defaultKeysResponse.error) {
			defaultKeys = defaultKeysResponse.data.default_keys;
		}
	}

	let subscription: api.SummarySubscription | undefined;
	if (grants.canReceiveSummaries) {
		const summarySubscriptionResponse = api.expandResponse(
			await api.getSummarySubscription(fetch, classId)
		);
		if (summarySubscriptionResponse.error) {
			console.error('Error fetching summary subscription:', summarySubscriptionResponse.error);
		} else {
			subscription = summarySubscriptionResponse.data;
		}
	}

	return {
		apiKey,
		classCredentials,
		apiKeyReadError,
		aiProvider,
		hasGeminiCredential,
		hasElevenlabsCredential,
		defaultKeys,
		grants,
		class: classDataResponse.data,
		subscription: subscription,
		canvasInstances: canvasInstances.data.instances,
		ltiClasses: ltiClasses.data.classes
	};
};
