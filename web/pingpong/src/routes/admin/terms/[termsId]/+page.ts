import type { PageLoad } from './$types';
import type { UserAgreementDetail } from '$lib/api';
import { getUserAgreementDetail, expandResponse } from '$lib/api';

export const load: PageLoad = async ({ params, fetch, parent }) => {
  const isCreating = params.termsId === 'new';
  let userAgreement: UserAgreementDetail | null = null;

  if (!isCreating) {
    const userAgreementResponse = await getUserAgreementDetail(
      fetch,
      parseInt(params.termsId, 10)
    ).then(expandResponse);

    userAgreement = userAgreementResponse.error ? null : userAgreementResponse.data;
  }

  return {
    isCreating,
    userAgreement
  };
};
