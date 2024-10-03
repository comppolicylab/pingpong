import type { LayoutLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';

export const load: LayoutLoad = async ({ fetch, parent }) => {
  const parentData = await parent();

  // Non admins should not be able to access this page.
  if (!parentData.admin.showAdminPage) {
    redirect(302, '/');
  }

  let statistics = null;
  const statisticsResponse = await api.getStatistics(fetch).then(api.expandResponse);
  if (statisticsResponse.data) {
    statistics = statisticsResponse.data.statistics;
  }

  const institutions: api.Institution[] = [];
  const seen = new Set<number>();
  for (const cls of parentData.classes) {
    if (cls.institution && !seen.has(cls.institution.id)) {
      seen.add(cls.institution.id);
      institutions.push(cls.institution);
    }
  }

  return { institutions, statistics };
};
