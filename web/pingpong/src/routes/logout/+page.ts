import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import { clearLTISessionToken } from '$lib/api';

export const load: PageLoad = async () => {
	if (browser) {
		document.cookie = 'session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
		clearLTISessionToken();
		redirect(302, '/');
	}
};
