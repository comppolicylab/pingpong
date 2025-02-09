import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, url }) => {
  const termsId = url.searchParams.get('id');

  if (!termsId) {
    return {
      agreement: null
    };
  }
  const agreementId = parseInt(termsId, 10);
  let agreement: api.UserAgreementDetail | null = null;
  const agreementsResponse = await api
    .getUserAgreementDetail(fetch, agreementId)
    .then(api.expandResponse);

  agreement = agreementsResponse.error ? null : agreementsResponse.data;

  return {
    agreement
  };
};
