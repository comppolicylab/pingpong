import type { LayoutLoad } from './$types';

/**
 * Load the current user and redirect if they are not logged in.
 */
export const load: LayoutLoad = async ({ url }) => {
	if (url.pathname === '/login') {
		return {
			showSidebar: false
		};
	}

	// Default layout
	return {
		showSidebar: true
	};
};
