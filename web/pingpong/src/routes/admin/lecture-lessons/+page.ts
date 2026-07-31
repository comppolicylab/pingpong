import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
	const response = await api.getLectureLessonAccessUsers(fetch).then(api.expandResponse);
	if (response.error) {
		error(response.$status || 500, response.error.detail || 'Failed to load lecture lesson access');
	}

	return {
		users: response.data?.users ?? []
	};
};
