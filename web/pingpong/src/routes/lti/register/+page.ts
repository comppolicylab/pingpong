import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
  const externalLoginProvidersResult = await api
    .getExternalLoginProvidersForLTI(fetch)
    .then(api.expandResponse);
  let externalLoginProviders: api.ExternalLoginProvider[] = [];
  if (externalLoginProvidersResult.error) {
    return {
      externalLoginProviders: []
    };
  }
  externalLoginProviders = externalLoginProvidersResult.data.providers;
  return {
    externalLoginProviders: externalLoginProviders
  };
};
