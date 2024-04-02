import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
  const [institutions, classes, grants] = await Promise.all([
    api
      .getInstitutions(fetch, 'can_create_class')
      .then(api.explodeResponse)
      .then((i) => i.institutions),
    api
      .getMyClasses(fetch)
      .then(api.explodeResponse)
      .then((c) => c.classes),
    api.grants(fetch, {
      canCreateInstitution: {
        target_type: 'root',
        target_id: 0,
        relation: 'can_create_institution',
      },
    })
  ]);
  return {
    institutions,
    classes,
    canCreateInstitution: grants.canCreateInstitution,
  };
};
