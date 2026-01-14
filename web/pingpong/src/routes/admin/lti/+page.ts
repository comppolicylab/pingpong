import { error, redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, parent }) => {
	const parentData = await parent();
	if (!parentData.admin?.isRootAdmin) {
		redirect(302, '/');
	}

	const registrations = await api.getLTIRegistrations(fetch).then(api.expandResponse);
	if (registrations.error) {
		error(
			registrations.$status || 500,
			registrations.error.detail || 'Failed to load LTI registrations'
		);
	}

	return {
		registrations: registrations.data?.registrations ?? []
	};
};
