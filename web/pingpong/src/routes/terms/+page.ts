import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, url }) => {
	const termsId = url.searchParams.get('id');

	if (!termsId) {
		return {
			agreement: null,
			policyId: null
		};
	}
	const policyId = parseInt(termsId, 10);
	let agreement: api.AgreementBody | null = null;
	const agreementsResponse = await api
		.getAgreementByPolicyId(fetch, policyId)
		.then(api.expandResponse);

	agreement = agreementsResponse.error ? null : agreementsResponse.data;

	return {
		agreement,
		policyId
	};
};
