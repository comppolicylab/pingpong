import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
  const subscriptionsResponse = await api.getActivitySummaries(fetch).then(api.expandResponse);

  let subscriptions: api.ActivitySummarySubscription[] = [];
  let subscriptionOpts: api.ActivitySummarySubscriptionAdvancedOpts = {
    dna_as_create: false,
    dna_as_join: false
  };
  if (subscriptionsResponse.data) {
    subscriptions = subscriptionsResponse.data.subscriptions.sort((a, b) =>
      a.class_name.localeCompare(b.class_name)
    );
    subscriptionOpts = subscriptionsResponse.data.advanced_opts;
  }

  return {
    subscriptions,
    subscriptionOpts
  };
};
