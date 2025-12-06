import { error, redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, parent, params }) => {
  const parentData = await parent();
  if (!parentData.admin?.isRootAdmin) {
    redirect(302, '/');
  }

  const institutionId = Number(params.id);
  const response = await api
    .getInstitutionWithAdmins(fetch, institutionId)
    .then(api.expandResponse);
  if (response.error || !response.data) {
    error(response.$status || 500, response.error?.detail || 'Failed to load institution');
  }

  return {
    institution: response.data
  };
};
