import type { PageLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, url }) => {
  const ltiClassIdParam = url.searchParams.get('lti_class_id');

  if (!ltiClassIdParam) {
    redirect(302, '/');
  }

  const ltiClassId = parseInt(ltiClassIdParam, 10);
  if (isNaN(ltiClassId)) {
    redirect(302, '/');
  }

  const [contextResult, groupsResult] = await Promise.all([
    api.getLTISetupContext(fetch, ltiClassId).then(api.expandResponse),
    api.getLTILinkableGroups(fetch, ltiClassId).then(api.expandResponse)
  ]);

  if (contextResult.error) {
    redirect(302, '/');
  }

  const groups = groupsResult.error ? [] : groupsResult.data.groups;

  return {
    context: contextResult.data,
    groups,
    ltiClassId
  };
};
