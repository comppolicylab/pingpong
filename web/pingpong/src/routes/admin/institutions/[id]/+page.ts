import { error, redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, parent, params }) => {
  const parentData = await parent();
  if (!parentData.admin?.isRootAdmin) {
    redirect(302, '/');
  }

  const institutionId = Number(params.id);
  const [institutionResponse, defaultKeysResponse] = await Promise.all([
    api.getInstitutionWithAdmins(fetch, institutionId).then(api.expandResponse),
    api.getDefaultAPIKeys(fetch).then(api.expandResponse)
  ]);
  if (institutionResponse.error || !institutionResponse.data) {
    error(
      institutionResponse.$status || 500,
      institutionResponse.error?.detail || 'Failed to load institution'
    );
  }
  if (defaultKeysResponse.error || !defaultKeysResponse.data) {
    error(
      defaultKeysResponse.$status || 500,
      defaultKeysResponse.error?.detail || 'Failed to load default API keys'
    );
  }

  return {
    institution: institutionResponse.data,
    defaultKeys: defaultKeysResponse.data.default_keys
  };
};
