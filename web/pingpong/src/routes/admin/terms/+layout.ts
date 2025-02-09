import type { LayoutLoad } from './$types';
import * as api from '$lib/api';

export const load: LayoutLoad = async ({ fetch }) => {
  const externalProviders = await api.getExternalLoginProviders(fetch).then(api.expandResponse);
  const categories = await api.getUserAgreementCategories(fetch).then(api.expandResponse);

  const sortedProviders = externalProviders.error
    ? []
    : externalProviders.data.providers.sort((a, b) => a.name.localeCompare(b.name));
  const sortedCategories = categories.error
    ? []
    : categories.data.categories.sort((a, b) => a.name.localeCompare(b.name));

  return {
    externalProviders: sortedProviders,
    categories: sortedCategories
  };
};
