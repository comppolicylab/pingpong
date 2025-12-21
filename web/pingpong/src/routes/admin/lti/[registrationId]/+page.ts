import { error, redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, parent, params }) => {
  const parentData = await parent();
  if (!parentData.admin?.isRootAdmin) {
    redirect(302, '/');
  }

  const registrationId = Number(params.registrationId);
  const [registrationResponse, institutionsResponse] = await Promise.all([
    api.getLTIRegistration(fetch, registrationId).then(api.expandResponse),
    api.getInstitutionsWithDefaultAPIKey(fetch).then(api.expandResponse)
  ]);

  if (registrationResponse.error || !registrationResponse.data) {
    error(
      registrationResponse.$status || 500,
      registrationResponse.error?.detail || 'Failed to load LTI registration'
    );
  }

  if (institutionsResponse.error || !institutionsResponse.data) {
    error(
      institutionsResponse.$status || 500,
      institutionsResponse.error?.detail || 'Failed to load institutions'
    );
  }

  return {
    registration: registrationResponse.data,
    availableInstitutions: institutionsResponse.data.institutions
  };
};
