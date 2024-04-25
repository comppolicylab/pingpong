import type { PageLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, parent }) => {
  const [institutions, grants] = await Promise.all([
    api
      .getInstitutions(fetch, 'can_create_class')
      .then(api.explodeResponse)
      .then((i) => i.institutions),
    api.grants(fetch, {
      canCreateInstitution: {
        target_type: 'root',
        target_id: 0,
        relation: 'can_create_institution'
      }
    })
  ]);

  // Generally we just want to redirect users to the class page.
  // We can redirect to the most recent class, or the first class they have access to.
  // If they have no classes, we'll just stay on this page and display a no-data state.
  // TODO - for admins, we should land on this page and show controls.
  const parentData = await parent();
  if (parentData.threads.length > 0) {
    return redirect(302, `/class/${parentData.threads[0].class_id}`);
  } else if (parentData.classes.length > 0) {
    return redirect(302, `/class/${parentData.classes[0].id}`);
  }

  return {
    institutions,
    canCreateInstitution: grants.canCreateInstitution
  };
};
