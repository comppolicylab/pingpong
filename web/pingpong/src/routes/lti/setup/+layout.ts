import type { LayoutLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';

const fallbackSupportInfo = {
	blurb: 'Need help with setup? Please contact your PingPong administrator or support team.',
	can_post: false
};

const parsePositiveInteger = (value: string | null): number | null => {
	if (!value || !/^[1-9]\d*$/.test(value)) return null;
	const parsed = Number(value);
	return Number.isSafeInteger(parsed) ? parsed : null;
};

export const load: LayoutLoad = async ({ fetch, url }) => {
	const ltiClassIdParam = url.searchParams.get('lti_class_id');
	const deepLinkSessionIdParam = url.searchParams.get('deep_link_session_id');

	const ltiClassId = parsePositiveInteger(ltiClassIdParam);
	if (ltiClassId === null) {
		redirect(302, '/');
	}
	const deepLinkSessionId = deepLinkSessionIdParam
		? parsePositiveInteger(deepLinkSessionIdParam)
		: null;
	if (deepLinkSessionIdParam && deepLinkSessionId === null) {
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
		deepLinkSessionId,
		supportInfo: supportResult.error ? fallbackSupportInfo : supportResult.data
	};
};
