import type { LayoutLoad } from './$types';
import * as api from '$lib/api';

export const load: LayoutLoad = async ({ fetch }) => {
	const externalProviders = await api.getExternalLoginProviders(fetch).then(api.expandResponse);
	const agreements = await api.listAgreements(fetch).then(api.expandResponse);

	const sortedProviders = externalProviders.error
		? []
		: externalProviders.data.providers.sort((a, b) => a.name.localeCompare(b.name));

	const sortedAgreements = agreements.error
		? []
		: agreements.data.agreements.sort(
				(a, b) =>
					new Date(a.updated ?? a.created).getTime() - new Date(b.updated ?? b.created).getTime()
			);

	return {
		externalProviders: sortedProviders,
		agreements: sortedAgreements
	};
};
