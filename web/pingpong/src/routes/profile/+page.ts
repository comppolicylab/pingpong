import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
  const subscriptionsResponse = await api.getActivitySummaries(fetch).then(api.expandResponse);

  let subscriptions: api.ActivitySummarySubscription[] = [];
  if (subscriptionsResponse.data) {
    subscriptions = subscriptionsResponse.data.subscriptions;
  }

  return {
    subscriptions
  };
};
