import type { LayoutLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';

export const load: LayoutLoad = async ({ parent }) => {
  const parentData = await parent();

  // Non admins should not be able to access this page.
  if (!parentData.admin.showAdminPage) {
    redirect(302, '/')
  }

  const institutions: api.Institution[] = [];
  const seen = new Set<number>();
  for (const cls of parentData.classes) {
      if (cls.institution && !seen.has(cls.institution.id)) {
          seen.add(cls.institution.id);
          institutions.push(cls.institution);
      }
  }

  return {institutions};
};
