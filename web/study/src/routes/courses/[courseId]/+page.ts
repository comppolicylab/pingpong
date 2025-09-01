import type { PageLoad } from './$types';

export const load: PageLoad = async () => {
	// Keep page non-blocking; data is fetched in +page.svelte
	return {
		title: 'Course Details'
	};
};
