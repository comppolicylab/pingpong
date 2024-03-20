import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
  return {
    institutions: api
      .getInstitutions(fetch, 'can_create_class')
      .then(api.explodeResponse)
      .then((i) => i.institutions),
    classes: api
      .getMyClasses(fetch)
      .then(api.explodeResponse)
      .then((c) => c.classes)
  };
};
