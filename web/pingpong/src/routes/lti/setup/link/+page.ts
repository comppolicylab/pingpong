import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, parent }) => {
	const { ltiClassId } = await parent();
	const groupsResult = await api.getLTILinkableGroups(fetch, ltiClassId).then(api.expandResponse);
	const groups = groupsResult.error ? [] : groupsResult.data.groups;

	return {
		groups
	};
};
