import { error, redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, url }) => {
	const rawSessionId = url.searchParams.get('deep_link_session_id');
	if (!rawSessionId) redirect(302, '/');
	const deepLinkSessionId = Number.parseInt(rawSessionId, 10);
	if (!Number.isInteger(deepLinkSessionId) || deepLinkSessionId <= 0) redirect(302, '/');

	const result = await api.getLTIDeepLinkContext(fetch, deepLinkSessionId).then(api.expandResponse);
	if (result.error || !result.data) {
		error(result.$status, result.error?.detail || 'Unable to load the Canvas selection.');
	}
	return { context: result.data, deepLinkSessionId };
};
