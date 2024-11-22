import type { LayoutLoad } from '../$types';
import * as api from '$lib/api';

export const load: LayoutLoad = async ({ fetch }) => {
  let defaultKeys: api.DefaultAPIKey[] = [];
  const defaultKeysResponse = await api.getDefaultAPIKeys(fetch).then(api.expandResponse);
  if (defaultKeysResponse.data) {
    defaultKeys = defaultKeysResponse.data.default_keys;
  }

  return { defaultKeys };
};
