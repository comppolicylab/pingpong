import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
  const userAgreements = await api.getUserAgreements(fetch).then(api.expandResponse);

  const sortedAgreements = userAgreements.error
    ? []
    : userAgreements.data.agreements.sort((a, b) => {
        if (a.category.id === b.category.id) {
          return new Date(a.effective_date).getTime() - new Date(b.effective_date).getTime();
        }
        return a.category.id - b.category.id;
      });
  return {
    agreements: sortedAgreements
  };
};
