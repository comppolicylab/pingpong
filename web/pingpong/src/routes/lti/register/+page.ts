import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
  const [externalLoginProvidersResult, institutionsResult] = await Promise.all([
    api.getPublicExternalLoginProvidersForLTI(fetch).then(api.expandResponse),
    api.getPublicInstitutionsForLTI(fetch).then(api.expandResponse)
  ]);

  const externalLoginProviders: api.LTIPublicSSOProvider[] = externalLoginProvidersResult.error
    ? []
    : externalLoginProvidersResult.data.providers;

  const institutions: api.LTIPublicInstitution[] = institutionsResult.error
    ? []
    : institutionsResult.data.institutions;

  return {
    externalLoginProviders,
    institutions
  };
};
