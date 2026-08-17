import { error, redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, url }) => {
	const rawSessionId = url.searchParams.get('deep_link_session_id');
	if (!rawSessionId) redirect(302, '/');
	const deepLinkSessionId = Number.parseInt(rawSessionId, 10);
	if (!Number.isInteger(deepLinkSessionId) || deepLinkSessionId <= 0) redirect(302, '/');

	const result = await api
		.getLTIDeepLinkContext(fetch, deepLinkSessionId)
		.then(api.expandResponse)
		.catch((requestError: unknown) => ({
			$status: 503,
			error: {
				detail: requestError instanceof Error ? requestError.message : 'An unknown error occurred.'
			},
			data: null
		}));
	if (result.error || !result.data) {
		const status = result.$status >= 400 && result.$status <= 599 ? result.$status : 500;
		error(status, result.error?.detail || 'Unable to load the Canvas selection.');
	}
	return { context: result.data, deepLinkSessionId };
};
