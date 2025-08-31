import type { PageLoad } from './$types';

export const load: PageLoad = async () => {
	// Keep page non-blocking; fetch happens in +page.svelte
	return {
		title: 'Pre-Assessment Details'
	};
};
