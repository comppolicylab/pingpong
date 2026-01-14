import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
	const externalProviders = await api.getExternalLoginProviders(fetch).then(api.expandResponse);

	const sortedProviders = externalProviders.error
		? []
		: externalProviders.data.providers.sort((a, b) => a.name.localeCompare(b.name));
	return {
		externalProviders: sortedProviders
	};
};
