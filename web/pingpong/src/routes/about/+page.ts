import type { PageLoad } from './$types';
import * as api from '$lib/api';

/**
 * Load the data for the about/support page.
 */
export const load: PageLoad = async ({ fetch }) => {
  const response = api.expandResponse(await api.getSupportInfo(fetch));

  if (response.error) {
    return {
      supportInfo: {
        blurb: `Error loading support information: ${response.error.detail || 'unknown error'}`,
        can_post: false
      }
    };
  }

  return {
    supportInfo: response.data
  };
};
