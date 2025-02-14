import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
  const policies = await api.listAgreementPolicies(fetch).then(api.expandResponse);

  const sortedPolicies = policies.error
    ? []
    : policies.data.policies.sort(
        (a, b) => new Date(a.not_before ?? '').getTime() - new Date(b.not_before ?? '').getTime()
      );
  return {
    policies: sortedPolicies
  };
};
