import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, url }) => {
	const openid_configuration = url.searchParams.get('openid_configuration');
	const registration_token = url.searchParams.get('registration_token');
	const providersPromise =
		openid_configuration && registration_token
			? api
					.getPublicExternalLoginProvidersForLTI(fetch, {
						openid_configuration,
						registration_token
					})
					.then(api.expandResponse)
			: Promise.resolve(null);

	const [externalLoginProvidersResult, institutionsResult] = await Promise.all([
		providersPromise,
		api.getPublicInstitutionsForLTI(fetch).then(api.expandResponse)
	]);

	const externalLoginProviders: api.LTIPublicSSOProvider[] =
		externalLoginProvidersResult && !externalLoginProvidersResult.error
			? externalLoginProvidersResult.data.providers
			: [];

	const institutions: api.LTIPublicInstitution[] = institutionsResult.error
		? []
		: institutionsResult.data.institutions;

	return {
		externalLoginProviders,
		institutions
	};
};
