import { error, redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, parent }) => {
  const parentData = await parent();
  if (!parentData.admin?.isRootAdmin) {
    redirect(302, '/');
  }

  const institutions = await api.getInstitutionsWithAdmins(fetch).then(api.expandResponse);
  if (institutions.error) {
    error(institutions.$status || 500, institutions.error.detail || 'Failed to load institutions');
  }

  return {
    institutions: institutions.data?.institutions ?? []
  };
};
