import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
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
  return {
    institutions,
    canCreateInstitution: grants.canCreateInstitution
  };
};
