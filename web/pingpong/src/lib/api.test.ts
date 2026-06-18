import { afterEach, describe, expect, it, vi } from 'vitest';

import { expandResponse, getClassUploadInfo, getThread, type Fetcher } from '$lib/api';
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

describe('getClassUploadInfo', () => {
	it('falls back to known extensions for generic browser MIME types', async () => {
		const fetcher = vi.fn().mockResolvedValue(
			new Response(
				JSON.stringify({
					types: [
						{
							name: 'Markdown',
							mime_type: 'text/markdown',
							file_search: true,
							code_interpreter: true,
							vision: false,
							input_file: true,
							extensions: ['md', 'markdown']
						},
						{
							name: 'Pickle',
							mime_type: 'application/octet-stream',
							file_search: false,
							code_interpreter: true,
							vision: false,
							input_file: false,
							extensions: ['pkl']
						}
					],
					allow_private: true,
					private_file_max_size: 1,
					class_file_max_size: 1
				}),
				{ status: 200, headers: { 'content-type': 'application/json' } }
			)
		) as unknown as Fetcher;

		const uploadInfo = await getClassUploadInfo(fetcher, 1);

		expect(uploadInfo.mimeType('application/octet-stream', 'notes.md')?.name).toBe('Markdown');
		expect(uploadInfo.mimeType('application/octet-stream', 'model.pkl')?.name).toBe('Pickle');
		expect(
			uploadInfo.getFileSupportFilter({ file_search: true })(
				new File(['# Notes'], 'notes.md', { type: 'application/octet-stream' })
			)
		).toBe(true);
		expect(uploadInfo.fileTypes({ file_search: true })).toContain('.md');
	});
});
