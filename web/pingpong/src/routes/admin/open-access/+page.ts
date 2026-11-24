import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';
import dayjs from '$lib/time';

const GRANULARITIES: api.OpenAccessGranularity[] = ['day', 'week', 'month'];

export const load: PageLoad = async ({ fetch, url }) => {
	const today = dayjs();
	const start = url.searchParams.get('start') ?? today.format('YYYY-MM-DD');
	const end = url.searchParams.get('end') ?? today.format('YYYY-MM-DD');
	const requested = url.searchParams.get('granularity') as api.OpenAccessGranularity | null;
	const granularity = requested && GRANULARITIES.includes(requested) ? requested : 'day';
	const response = await api
		.getOpenAccessUsage(fetch, {
			start,
			end,
			granularity,
			tz: Intl.DateTimeFormat().resolvedOptions().timeZone
		})
		.then(api.expandResponse);
	if (response.error || !response.data) {
		error(response.$status || 500, response.error?.detail || 'Failed to load Open Access usage');
	}
	return { usage: response.data, start, end, granularity };
};
