import { get } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';

import * as api from '$lib/api';
import type { BaseResponse, Fetcher, ThreadWithMeta } from '$lib/api';
import { parseTextContent } from '$lib/content';

import { ThreadManager } from './thread';

const ttsMocks = vi.hoisted(() => ({
	unlockSharedAudioContext: vi.fn(),
	getSharedAudioContext: vi.fn(() => null),
	createPlayer: vi.fn()
}));

vi.mock('$lib/wavtools/index', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/wavtools/index')>();
	return {
		...actual,
		unlockSharedAudioContext: ttsMocks.unlockSharedAudioContext,
		getSharedAudioContext: ttsMocks.getSharedAudioContext,
		WavStreamPlayer: function (options: unknown) {
			return ttsMocks.createPlayer(options);
		} as unknown as typeof import('$lib/wavtools/index').WavStreamPlayer
	};
});

describe('ThreadManager', () => {
	afterEach(() => {
		vi.restoreAllMocks();
		ttsMocks.unlockSharedAudioContext.mockClear();
		ttsMocks.getSharedAudioContext.mockClear();
		ttsMocks.createPlayer.mockReset();
	});

	const makeFakePlayer = (connect: () => Promise<true>) => ({
		connect: vi.fn(connect),
		setVolume: vi.fn(),
		add16BitPCM: vi.fn(),
		finish: vi.fn(),
		interrupt: vi.fn().mockResolvedValue(null),
		close: vi.fn().mockResolvedValue(undefined)
	});

	const makeChunks = (chunks: api.ThreadStreamChunk[]) => {
		const stream = new ReadableStream<object>({
			start(controller) {
				controller.close();
			}
		});
		return {
			stream,
			reader: stream.getReader(),
			async *[Symbol.asyncIterator]() {
				yield* chunks;
			}
		} as Awaited<ReturnType<typeof api.postMessage>>;
	};

	const makeAssistantMessage = (id: string): api.OpenAIMessage => ({
		id,
		role: 'assistant',
		content: [],
		created_at: Date.now() / 1000 + 5,
		metadata: {},
		assistant_id: 'asst_1',
		object: 'thread.message',
		run_id: 'run_tts_1',
		attachments: []
	});

	const textDelta = (value: string): api.ThreadStreamChunk =>
		({
			type: 'message_delta',
			delta: {
				content: [{ index: 0, type: 'text', text: { value, annotations: [] } }],
				role: null
			}
		}) as unknown as api.ThreadStreamChunk;
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

	it('preserves code interpreter call ids on grouped output image content', () => {
		const threadData = makeThreadData();
		threadData.ci_messages = [
			{
				id: 'ci-message-1',
				assistant_id: 'asst_SiulxBT6Y6bxpzDqJnQB9Vpp',
				content: [
					{
						type: 'code_output_image_file',
						image_file: { file_id: 'file-ci-image' }
					},
					{
						type: 'code_output_logs',
						logs: 'plot saved'
					}
				],
				created_at: 1773127553,
				metadata: {
					ci_call_id: '6'
				},
				object: 'thread.message',
				message_type: 'code_interpreter_call',
				role: 'assistant',
				run_id: 'run_a5OTi6XDw5tlAH0ZgeJGfvIW',
				attachments: []
			}
		];

		const manager = new ThreadManager(vi.fn() as unknown as Fetcher, 1, 181, threadData, 'voice');
		const [mergedMessage] = get(manager.messages);
		const imageContent = mergedMessage.data.content.find(
			(content) => content.type === 'code_output_image_file'
		);
		const logsContent = mergedMessage.data.content.find(
			(content) => content.type === 'code_output_logs'
		);

		expect(imageContent?.ci_call_id).toBe('6');
		expect(imageContent?.source_message_id).toBe('ci-message-1');
		expect(logsContent).not.toHaveProperty('ci_call_id');
		expect(logsContent?.source_message_id).toBe('ci-message-1');
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

	it('keeps streaming text when the TTS player never finishes connecting', async () => {
		const player = makeFakePlayer(() => new Promise<true>(() => {}));
		ttsMocks.createPlayer.mockReturnValue(player);
		vi.spyOn(api, 'postMessage').mockResolvedValue(
			makeChunks([
				{
					type: 'message_created',
					role: 'assistant',
					message: makeAssistantMessage('msg_tts_1')
				} as unknown as api.ThreadStreamChunk,
				{ type: 'audio_started' } as api.ThreadStreamChunk,
				textDelta('Hello'),
				{ type: 'audio_delta', audio: 'AAAA' } as api.ThreadStreamChunk,
				textDelta(' world'),
				{ type: 'audio_done' } as api.ThreadStreamChunk,
				{ type: 'done' } as api.ThreadStreamChunk
			])
		);

		const manager = new ThreadManager(
			vi.fn() as unknown as Fetcher,
			1,
			181,
			makeThreadData('lecture_video'),
			'lecture_video'
		);
		await manager.postMessage(123, 'Hi', vi.fn());

		// The audio context was unlocked while the send gesture was live.
		expect(ttsMocks.unlockSharedAudioContext).toHaveBeenCalledWith(24000);

		// Text rendered fully even though connect() is still pending.
		const assistantMessage = get(manager.messages).find((m) => m.data.id === 'msg_tts_1');
		const textContent = assistantMessage?.data.content.find((c) => c.type === 'text');
		if (textContent?.type !== 'text') {
			throw new Error('Expected streamed text content.');
		}
		expect(textContent.text.value).toBe('Hello world');
		expect(player.add16BitPCM).not.toHaveBeenCalled();
	});

	it('flushes audio buffered while the TTS player was connecting', async () => {
		const player = makeFakePlayer(() => Promise.resolve(true as const));
		ttsMocks.createPlayer.mockReturnValue(player);
		vi.spyOn(api, 'postMessage').mockResolvedValue(
			makeChunks([
				{
					type: 'message_created',
					role: 'assistant',
					message: makeAssistantMessage('msg_tts_2')
				} as unknown as api.ThreadStreamChunk,
				{ type: 'audio_started' } as api.ThreadStreamChunk,
				{ type: 'audio_delta', audio: 'AAAA' } as api.ThreadStreamChunk,
				{ type: 'audio_delta', audio: 'BBBB' } as api.ThreadStreamChunk,
				{ type: 'audio_done' } as api.ThreadStreamChunk,
				{ type: 'done' } as api.ThreadStreamChunk
			])
		);

		const manager = new ThreadManager(
			vi.fn() as unknown as Fetcher,
			1,
			181,
			makeThreadData('lecture_video'),
			'lecture_video'
		);
		await manager.postMessage(123, 'Hi', vi.fn());

		// Player setup is fire-and-forget, so wait for the flush to land.
		await vi.waitFor(() => {
			expect(player.add16BitPCM).toHaveBeenCalledTimes(2);
			expect(player.finish).toHaveBeenCalledTimes(1);
		});
		expect(player.setVolume).toHaveBeenCalled();
	});

	it('does not unlock the audio context when voice is muted or outside lessons', async () => {
		vi.spyOn(api, 'postMessage').mockResolvedValue(makeChunks([]));

		const mutedManager = new ThreadManager(
			vi.fn() as unknown as Fetcher,
			1,
			181,
			makeThreadData('lecture_video'),
			'lecture_video'
		);
		mutedManager.setTtsMuted(true);
		await mutedManager.postMessage(123, 'Hello', vi.fn());
		expect(ttsMocks.unlockSharedAudioContext).not.toHaveBeenCalled();

		const chatManager = new ThreadManager(
			vi.fn() as unknown as Fetcher,
			1,
			181,
			makeThreadData('voice'),
			'voice'
		);
		await chatManager.postMessage(123, 'Hello', vi.fn());
		expect(ttsMocks.unlockSharedAudioContext).not.toHaveBeenCalled();
	});
});
