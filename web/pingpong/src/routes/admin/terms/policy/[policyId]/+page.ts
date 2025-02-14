import type { PageLoad } from './$types';
import type { AgreementPolicyDetail } from '$lib/api';
import { getAgreementPolicy, expandResponse } from '$lib/api';

export const load: PageLoad = async ({ params, fetch, parent }) => {
  const isCreating = params.policyId === 'new';
  let agreementPolicy: AgreementPolicyDetail | null = null;

  if (!isCreating) {
    const agreementPolicyResponse = await getAgreementPolicy(
      fetch,
      parseInt(params.policyId, 10)
    ).then(expandResponse);

    agreementPolicy = agreementPolicyResponse.error ? null : agreementPolicyResponse.data;
  }

  return {
    isCreating,
    agreementPolicy
  };
};
