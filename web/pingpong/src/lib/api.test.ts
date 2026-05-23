import { afterEach, describe, expect, it, vi } from 'vitest';

import { expandResponse, getThread, type Fetcher } from '$lib/api';
import { resetAnonymousShareToken, setAnonymousShareToken } from '$lib/stores/anonymous';

describe('getThread', () => {
	afterEach(() => {
		resetAnonymousShareToken();
	});

	it('sends the lecture video controller session header without dropping share tokens', async () => {
		const fetcher = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({}), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			})
		) as unknown as Fetcher;

		setAnonymousShareToken('share-token');
		const abortController = new AbortController();

		await getThread(fetcher, 1, 2, 'controller-session', abortController.signal);

		expect(fetcher).toHaveBeenCalledWith(
			'/api/v1/class/1/thread/2',
			expect.objectContaining({
				method: 'GET',
				headers: {
					'X-Anonymous-Link-Share': 'share-token',
					'X-Lecture-Video-Controller-Session': 'controller-session'
				},
				signal: abortController.signal
			})
		);
	});
});

describe('expandResponse', () => {
	it('normalizes coded HTTP error detail payloads', () => {
		const response = {
			$status: 409,
			detail: {
				message: 'This page was inactive for too long. Refresh the lesson to continue.',
				error_code: 'controller_lease_expired'
			}
		} as unknown as Parameters<typeof expandResponse>[0];
		const expanded = expandResponse(response);

		expect(expanded.error).toEqual({
			detail: 'This page was inactive for too long. Refresh the lesson to continue.',
			error_code: 'controller_lease_expired'
		});
	});
});
