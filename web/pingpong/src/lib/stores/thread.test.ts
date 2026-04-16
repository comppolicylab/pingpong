import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

import * as api from '$lib/api';
import type { BaseResponse, Fetcher, ThreadWithMeta } from '$lib/api';
import { parseTextContent } from '$lib/content';

import { ThreadManager } from './thread';

describe('ThreadManager', () => {
	const makeThreadData = (
		interactionMode: 'chat' | 'voice' | 'lecture_video' = 'voice'
	): BaseResponse & ThreadWithMeta => ({
		$status: 200,
		thread: {
			id: 181,
			name: null,
			version: 2,
			interaction_mode: interactionMode,
			class_id: 1,
			assistant_id: 1,
			private: true,
			tools_available: 'code_interpreter',
			created: '2026-03-10T00:00:00Z',
			last_activity: '2026-03-10T00:00:00Z'
		},
		model: 'gpt-4o',
		tools_available: 'code_interpreter',
		run: null,
		limit: 20,
		messages: [
			{
				id: 'msg_ICwP5UwBRji5qSzXjI8VhIds',
				assistant_id: 'asst_SiulxBT6Y6bxpzDqJnQB9Vpp',
				content: [
					{
						type: 'text',
						text: {
							value:
								'Here is a CSV file containing 10 random emails:\n\n[Download random_emails.csv](sandbox:/mnt/data/random_emails.csv)',
							annotations: [
								{
									type: 'file_path',
									start_index: 78,
									end_index: 113,
									text: 'sandbox:/mnt/data/random_emails.csv',
									file_path: {
										file_id: 'file-UTjpmNMy2UTjLgg1V8PYBS'
									}
								}
							]
						}
					}
				],
				created_at: 1773127557,
				metadata: {},
				object: 'thread.message',
				role: 'assistant',
				run_id: 'run_a5OTi6XDw5tlAH0ZgeJGfvIW',
				attachments: []
			}
		],
		ci_messages: [
			{
				id: '1',
				assistant_id: 'asst_SiulxBT6Y6bxpzDqJnQB9Vpp',
				content: [
					{
						type: 'code_interpreter_call_placeholder',
						run_id: 'run_a5OTi6XDw5tlAH0ZgeJGfvIW',
						step_id: 'step_kzhuM4gr6reS9xlUXCGf1ECi'
					}
				],
				created_at: 1773127553,
				metadata: {
					step_id: 'step_kzhuM4gr6reS9xlUXCGf1ECi'
				},
				object: 'code_interpreter_call_placeholder',
				message_type: null,
				role: 'assistant',
				run_id: 'run_a5OTi6XDw5tlAH0ZgeJGfvIW',
				attachments: []
			}
		],
		fs_messages: [],
		ws_messages: [],
		mcp_messages: [],
		reasoning_messages: [],
		attachments: {},
		instructions: null,
		recording: null,
		has_more: false
	});

	it('uses the originating server message id for v2 file links in grouped assistant content', () => {
		const threadData = makeThreadData();

		const manager = new ThreadManager(vi.fn() as unknown as Fetcher, 1, 181, threadData, 'voice');
		const [mergedMessage] = get(manager.messages);

		expect(mergedMessage.data.content).toHaveLength(2);
		expect(mergedMessage.data.content[0].source_message_id).toBe('1');

		const textContent = mergedMessage.data.content[1];
		expect(textContent.type).toBe('text');
		if (textContent.type !== 'text') {
			throw new Error('Expected text content.');
		}

		expect(textContent.source_message_id).toBe('msg_ICwP5UwBRji5qSzXjI8VhIds');

		const parsed = parseTextContent(
			textContent.text,
			2,
			'/api/v1/class/1/thread/181',
			textContent.source_message_id
		);

		expect(parsed.content).toContain(
			'/api/v1/class/1/thread/181/message/msg_ICwP5UwBRji5qSzXjI8VhIds/file/file-UTjpmNMy2UTjLgg1V8PYBS'
		);
		expect(parsed.content).not.toContain('/message/1/file/file-UTjpmNMy2UTjLgg1V8PYBS');
	});

	it('only sends generate_speech for lecture video threads', async () => {
		const stream = new ReadableStream<object>({
			start(controller) {
				controller.close();
			}
		});
		const emptyChunks: Awaited<ReturnType<typeof api.postMessage>> = {
			stream,
			reader: stream.getReader(),
			async *[Symbol.asyncIterator]() {}
		};
		const postMessageSpy = vi.spyOn(api, 'postMessage').mockResolvedValue(emptyChunks);

		const voiceManager = new ThreadManager(
			vi.fn() as unknown as Fetcher,
			1,
			181,
			makeThreadData('voice'),
			'voice'
		);
		await voiceManager.postMessage(123, 'Hello', vi.fn());
		expect(postMessageSpy).toHaveBeenNthCalledWith(
			1,
			expect.any(Function),
			1,
			181,
			expect.not.objectContaining({ generate_speech: expect.anything() })
		);

		const lectureManager = new ThreadManager(
			vi.fn() as unknown as Fetcher,
			1,
			181,
			makeThreadData('lecture_video'),
			'lecture_video'
		);
		lectureManager.setTtsMuted(true);
		await lectureManager.postMessage(123, 'Hello', vi.fn());
		expect(postMessageSpy).toHaveBeenNthCalledWith(
			2,
			expect.any(Function),
			1,
			181,
			expect.objectContaining({ generate_speech: false })
		);
	});
});
