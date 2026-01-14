import type { PageLoad } from './$types';
import type { AgreementDetail } from '$lib/api';
import { getAgreement, expandResponse } from '$lib/api';

export const load: PageLoad = async ({ params, fetch }) => {
	const isCreating = params.agreementId === 'new';
	let userAgreement: AgreementDetail | null = null;

	if (!isCreating) {
		const userAgreementResponse = await getAgreement(fetch, parseInt(params.agreementId, 10)).then(
			expandResponse
		);

		userAgreement = userAgreementResponse.error ? null : userAgreementResponse.data;
	}

	return {
		isCreating,
		userAgreement
	};
};
