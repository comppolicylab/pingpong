import { expandResponse } from '$lib/api/utils';
import { me as getMe } from '$lib/api/client';
import type { LayoutLoad } from './$types';
import { redirect, error } from '@sveltejs/kit';
import type { Course } from '$lib/api/types';

const LOGIN = '/login';
const LOGOUT = '/logout';
/**
 * Load the current user and redirect if they are not logged in.
 */
export const load: LayoutLoad = async ({ fetch, url }) => {
	// Fetch the current user
	const me = expandResponse(await getMe(fetch));

	// If we can't even load `me` then the server is probably down.
	// Redirect to the login page if we're not already there, just
	// in case that will work. Otherwise, just show the error.
	if (me.error) {
		if (url.pathname !== LOGIN) {
			throw redirect(302, LOGIN);
		} else {
			const errorObject = (me.error || {}) as { $status: number; detail: string };
			const code = errorObject.$status || 500;
			const message = errorObject.detail || 'An unknown error occurred.';
			throw error(code, { message: `Error reaching the server: ${message}` });
		}
	}

	let showSidebar = true;
	const authed = me.data.status === 'valid';
	// If we're on the login page, we don't need the sidebar.
	if (url.pathname === LOGIN) {
		if (authed) {
			const destination = url.searchParams.get('forward') || '/';
			throw redirect(302, destination);
		} else {
			showSidebar = false;
		}
	} else if (!authed && url.pathname !== LOGOUT) {
		showSidebar = false;
		const destination = encodeURIComponent(`${url.pathname}${url.search}`);
		throw redirect(302, `${LOGIN}?forward=${destination}`);
	}

	return {
		showSidebar,
		// Defer course fetching to page/components to avoid blocking nav
		courses: [] as Course[],
		instructor: me.data.instructor
	};
};
