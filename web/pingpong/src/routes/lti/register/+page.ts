import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, url }) => {
	const openid_configuration = url.searchParams.get('openid_configuration');
	const registration_token = url.searchParams.get('registration_token');
	const registrationSetupResult =
		openid_configuration && registration_token
			? await api
					.getLTIRegisterSetup(fetch, {
						openid_configuration,
						registration_token
					})
					.then(api.expandResponse)
			: null;

	return {
		registrationSetup:
			registrationSetupResult && !registrationSetupResult.error
				? registrationSetupResult.data
				: null
	};
};
