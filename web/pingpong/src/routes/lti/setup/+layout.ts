import type { LayoutLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';

const fallbackSupportInfo = {
	blurb: 'Need help with setup? Please contact your PingPong administrator or support team.',
	can_post: false
};

export const load: LayoutLoad = async ({ fetch, url }) => {
	const ltiClassIdParam = url.searchParams.get('lti_class_id');

	if (!ltiClassIdParam) {
		redirect(302, '/');
	}

	const ltiClassId = parseInt(ltiClassIdParam, 10);
	if (isNaN(ltiClassId)) {
		redirect(302, '/');
	}

	const [contextResult, supportResult] = await Promise.all([
		api.getLTISetupContext(fetch, ltiClassId).then(api.expandResponse),
		api.getSupportInfo(fetch).then(api.expandResponse)
	]);

	if (contextResult.error) {
		redirect(302, '/');
	}

	return {
		context: contextResult.data,
		ltiClassId,
		supportInfo: supportResult.error ? fallbackSupportInfo : supportResult.data
	};
};
