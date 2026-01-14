import { writable, derived, get } from 'svelte/store';
import type { Writable, Readable } from 'svelte/store';
import * as api from '$lib/api';
import type { ThreadWithMeta, Error, BaseResponse } from '$lib/api';
import { Deferred } from '$lib/deferred';

/**
 * State for the thread manager.
 */
export type ThreadManagerState = {
	data: (BaseResponse & ThreadWithMeta) | null;
	error: ErrorWithSent | null;
	optimistic: api.OpenAIMessage[];
	limit: number;
	canFetchMore: boolean;
	loading: boolean;
	waiting: boolean;
	submitting: boolean;
	supportsFileSearch: boolean;
	supportsCodeInterpreter: boolean;
	attachments: Record<string, api.ServerFile>;
	instructions?: string | null;
};

export type ErrorWithSent = {
	detail?: string;
	wasSent: boolean;
};

export type CallbackParams = {
	success: boolean;
	errorMessage: string | null;
	message_sent: boolean;
};

/**
 * A message in a thread.
 */
export type Message = {
	data: api.OpenAIMessage;
	error: Error | null;
	persisted: boolean;
};

function getOrderValue(a: api.OpenAIMessage, b: api.OpenAIMessage): [number, number] {
	const aRunId = a.run_id ?? null;
	const bRunId = b.run_id ?? null;

	// If both messages are from the same run, compare by output_index
	if (aRunId !== null && bRunId !== null && aRunId === bRunId) {
		const aHasOutputIndex = typeof a.output_index === 'number';
		const bHasOutputIndex = typeof b.output_index === 'number';
		if (aHasOutputIndex && bHasOutputIndex) {
			return [a.output_index as number, b.output_index as number];
		}
		const aHasMetadataIndex = a.metadata && !isNaN(Number(a.metadata.output_index));
		const bHasMetadataIndex = b.metadata && !isNaN(Number(b.metadata.output_index));
		if (aHasMetadataIndex && bHasMetadataIndex) {
			return [Number(a.metadata?.output_index), Number(b.metadata?.output_index)];
		}
	}

	// Different runs or missing run_id: compare by created_at to maintain chronological order
	const aCreated = typeof a.created_at === 'number' ? a.created_at : 0;
	const bCreated = typeof b.created_at === 'number' ? b.created_at : 0;
	return [aCreated, bCreated];
}

const compareMessageDataAsc = (a: Message, b: Message) => {
	const [aVal, bVal] = getOrderValue(a.data, b.data);
	return aVal - bVal;
};
const compareMessageDataDesc = (a: Message, b: Message) => {
	const [aVal, bVal] = getOrderValue(a.data, b.data);
	return bVal - aVal;
};
const compareApiMessagesAsc = (a: api.OpenAIMessage, b: api.OpenAIMessage) => {
	const [aVal, bVal] = getOrderValue(a, b);
	return aVal - bVal;
};
const compareApiMessagesDesc = (a: api.OpenAIMessage, b: api.OpenAIMessage) => {
	const [aVal, bVal] = getOrderValue(a, b);
	return bVal - aVal;
};

/**
 * Manager for a single conversation thread.
 */
export class ThreadManager {
	/**
	 * The ID of the class this thread is in.
	 */
	classId: number;

	/**
	 * The ID of the thread.
	 */
	threadId: number;

	/**
	 * The current list of messages in the thread.
	 */
	messages: Readable<Message[]>;

	/**
	 * The current list of messages in the thread.
	 */
	attachments: Readable<Record<string, api.ServerFile>>;

	/**
	 * Whether the thread data is currently being loaded.
	 */
	loading: Readable<boolean>;

	/**
	 * Whether a message is currently being generated.
	 */
	waiting: Readable<boolean>;

	/**
	 * Whether a message is currently being submitted.
	 */
	submitting: Readable<boolean>;

	/**
	 * The users + assistants in the thread.
	 */
	participants: Readable<api.ThreadParticipants>;

	/**
	 * Whether the thread is published.
	 */
	published: Readable<boolean>;

	/**
	 * The ID of the assistant for this thread.
	 */
	assistantId: Readable<number | null>;

	/**
	 * Whether more messages can be fetched.
	 */
	canFetchMore: Readable<boolean>;

	/**
	 * Any error that occurred while fetching the thread.
	 */
	error: Readable<ErrorWithSent | null>;

	/**
	 * The user's timezone.
	 */
	timezone?: string;

	/**
	 * The thread instructions, if any.
	 */
	instructions: Readable<string | null>;

	version: Readable<number>;

	#data: Writable<ThreadManagerState>;
	#fetcher: api.Fetcher;

	/**
	 * Create a new thread manager.
	 */
	constructor(
		fetcher: api.Fetcher,
		classId: number,
		threadId: number,
		threadData: BaseResponse & (ThreadWithMeta | Error | api.ValidationError),
		interactionMode: 'chat' | 'voice' = 'chat',
		timezone?: string
	) {
		const expanded = api.expandResponse(threadData);
		this.#fetcher = fetcher;
		this.classId = classId;
		this.threadId = threadId;
		this.timezone = timezone;
		this.#data = writable({
			data: expanded.data || null,
			error: expanded.error ? { detail: expanded.error?.detail, wasSent: true } : null,
			limit: expanded.data?.limit || 20,
			canFetchMore: expanded.data?.has_more || false,
			supportsFileSearch: expanded.data?.thread?.tools_available?.includes('file_search') || false,
			supportsCodeInterpreter:
				expanded.data?.thread?.tools_available?.includes('code_interpreter') || false,
			optimistic: [],
			loading: false,
			waiting: false,
			submitting: false,
			attachments: expanded.data?.attachments || {},
			instructions: expanded.data?.instructions || null
		});

		if (interactionMode === 'chat') {
			this.#ensureRun(threadData);
		}

		this.messages = derived(this.#data, ($data) => {
			if (!$data) {
				return [];
			}
			const realMessages = ($data.data?.messages || []).map((message) => ({
				data: message,
				error: null,
				persisted: true
			}));
			const ci_messages = ($data.data?.ci_messages || []).map((message) => ({
				data: message,
				error: null,
				persisted: true
			}));
			const fs_messages = ($data.data?.fs_messages || []).map((message) => ({
				data: message,
				error: null,
				persisted: true
			}));
			const ws_messages = ($data.data?.ws_messages || []).map((message) => ({
				data: message,
				error: null,
				persisted: true
			}));
			const mcp_messages = ($data.data?.mcp_messages || []).map((message) => ({
				data: message,
				error: null,
				persisted: true
			}));
			const reasoning_messages = ($data.data?.reasoning_messages || []).map((message) => ({
				data: message,
				error: null,
				persisted: true
			}));
			const optimisticMessages = $data.optimistic.map((message) => ({
				data: message,
				error: null,
				persisted: false
			}));

			const allMessages = realMessages
				.concat(ci_messages)
				.concat(fs_messages)
				.concat(ws_messages)
				.concat(mcp_messages)
				.concat(reasoning_messages)
				.concat(optimisticMessages)
				.sort(compareMessageDataAsc);

			const finalMessages: Message[] = [];
			for (let i = 0; i < allMessages.length; ) {
				const current = allMessages[i];

				if (current.data.role !== 'assistant') {
					finalMessages.push(current);
					i += 1;
					continue;
				}

				const currentRunId = current.data.run_id ?? null;
				const group: Message[] = [current];
				let j = i + 1;

				while (j < allMessages.length) {
					const next = allMessages[j];
					if (next.data.role !== 'assistant') {
						break;
					}
					const nextRunId = next.data.run_id ?? null;
					if (nextRunId !== currentRunId) {
						break;
					}
					group.push(next);
					j += 1;
				}

				if (group.length === 1) {
					finalMessages.push(current);
				} else {
					const responseIndex = group.findIndex((message) => !message.data.message_type);
					const base = responseIndex >= 0 ? group[responseIndex] : group[0];
					const mergedContent = group.flatMap((message) => message.data.content || []);

					const merged: Message = {
						...base,
						data: {
							...base.data,
							content: mergedContent
						}
					};

					finalMessages.push(merged);
				}

				i = j;
			}

			const firstMessage = finalMessages[0];
			if (firstMessage?.data.role === 'user') {
				const hasAttachments = (firstMessage.data.attachments || []).length > 0;
				const hasMeaningfulContent = (firstMessage.data.content || []).some((content) => {
					if (content.type === 'text') {
						const value = content.text?.value || '';
						return value.trim().length > 0;
					}
					return true;
				});

				if (!hasAttachments && !hasMeaningfulContent) {
					finalMessages.shift();
				}
			}

			return finalMessages;
		});

		this.loading = derived(this.#data, ($data) => !!$data?.loading);

		this.waiting = derived(this.#data, ($data) => !!$data?.waiting);

		this.submitting = derived(this.#data, ($data) => !!$data?.submitting);

		this.assistantId = derived(this.#data, ($data) => {
			if ($data?.data?.thread?.assistant_names && $data?.data?.thread?.assistant_names[0]) {
				return 0;
			}

			return $data?.data?.thread?.assistant_id || null;
		});
		this.canFetchMore = derived(this.#data, ($data) => !!$data?.canFetchMore);

		this.published = derived(this.#data, ($data) => $data?.data?.thread?.private === false);

		this.error = derived(this.#data, ($data) => $data?.error || null);

		this.participants = derived(this.#data, ($data) => {
			return {
				user: $data?.data?.thread?.user_names || [],
				assistant: $data?.data?.thread?.assistant_names || {}
			};
		});

		this.attachments = derived(this.#data, ($data) => {
			return $data?.attachments || {};
		});

		this.instructions = derived(this.#data, ($data) => {
			return $data?.instructions || null;
		});

		this.version = derived(this.#data, ($data) => {
			return $data?.data?.thread?.version || 2;
		});
	}

	async #ensureRun(threadData: BaseResponse & (ThreadWithMeta | Error)) {
		// Only run this in the browser
		if (typeof window === 'undefined') {
			return;
		}

		const expanded = api.expandResponse(threadData);
		if (!expanded.data) {
			return;
		}

		// Check if the run is in progress. If it is, we'll need to poll until it's done;
		// streaming is not available.
		if (expanded.data.run && expanded.data.run.status !== 'pending') {
			if (!api.finished(expanded.data.run)) {
				await this.#pollThread();
				return;
			}
			// Otherwise, if the last run is finished, we can just display the results.
			return;
		}

		this.#data.update((d) => ({ ...d, submitting: true }));
		const chunks = await api.createThreadRun(this.#fetcher, this.classId, this.threadId, {
			timezone: this.timezone
		});
		try {
			await this.#handleStreamChunks(chunks);
		} catch (e) {
			if (e instanceof api.StreamError) {
				this.#data.update((d) => ({
					...d,
					error: { detail: e.message, wasSent: true },
					submitting: false
				}));
			} else if (e instanceof api.PresendError) {
				this.#data.update((d) => ({
					...d,
					error: { detail: e.message, wasSent: false },
					submitting: false
				}));
			} else if (e instanceof api.RunActiveError) {
				this.#data.update((d) => ({
					...d,
					error: { detail: e.message, wasSent: false },
					submitting: false
				}));
			} else {
				this.#data.update((d) => ({ ...d, error: { detail: (e as Error).detail, wasSent: true } }));
			}
		}
	}

	/**
	 * Poll the thread until the run is finished.
	 */
	async #pollThread(timeout: number = 120_000) {
		this.#data.update((d) => ({ ...d, waiting: true }));

		const deferred = new Deferred();

		const t0 = Date.now();
		const interval = setInterval(async () => {
			const response = await api.getThread(this.#fetcher, this.classId, this.threadId);
			const expanded = api.expandResponse(response);
			if (api.finished(expanded.data?.run)) {
				clearInterval(interval);
				this.#data.update((d) => ({
					...d,
					data: expanded.data,
					error: expanded.error ? { detail: expanded.error?.detail, wasSent: true } : null,
					waiting: false
				}));
				deferred.resolve();
				return;
			}

			if (Date.now() - t0 > timeout) {
				clearInterval(interval);
				this.#data.update((d) => ({
					...d,
					error: { detail: 'The thread run took too long to complete.', wasSent: true },
					waiting: false
				}));
				deferred.reject(new Error('The thread run took too long to complete.'));
			}
		}, 5000);

		return deferred.promise;
	}

	/**
	 * Delete the current thread.
	 */
	async delete() {
		this.#data.update((d) => ({ ...d, loading: true, error: null }));
		try {
			const result = api.expandResponse(
				await api.deleteThread(this.#fetcher, this.classId, this.threadId)
			);
			if (result.error) {
				throw result.error;
			}
			this.#data.update((d) => ({ ...d, loading: false }));
		} catch (e) {
			this.#data.update((d) => ({
				...d,
				error: { detail: (e as Error).detail, wasSent: true },
				loading: false
			}));
			throw e;
		}
	}

	/**
	 * Publish the current thread.
	 */
	async publish() {
		this.#data.update((d) => ({ ...d, loading: true, error: null }));
		try {
			await api.publishThread(this.#fetcher, this.classId, this.threadId);
			this.#data.update((d) => ({ ...d, loading: false }));
		} catch (e) {
			this.#data.update((d) => ({
				...d,
				error: { detail: (e as Error).detail, wasSent: true },
				loading: false
			}));
			throw e;
		}
	}

	/**
	 * Unpublish the current thread.
	 */
	async unpublish() {
		this.#data.update((d) => ({ ...d, loading: true, error: null }));
		try {
			await api.unpublishThread(this.#fetcher, this.classId, this.threadId);
			this.#data.update((d) => ({ ...d, loading: false }));
		} catch (e) {
			this.#data.update((d) => ({
				...d,
				error: { detail: (e as Error).detail, wasSent: true },
				loading: false
			}));
			throw e;
		}
	}

	/**
	 * Fetch an earlier page of results.
	 */
	async fetchMore() {
		const currentData = get(this.#data);
		if (currentData.loading || !currentData.canFetchMore) {
			return;
		}

		this.#data.update((d) => ({ ...d, error: null, loading: true }));
		const sortedMessages = [...(currentData.data?.messages || [])].sort(compareApiMessagesAsc);
		const earliestMessage = sortedMessages[0];
		const earliestRunMessage = sortedMessages.find((message) => message.run_id);
		const threadVersion = currentData.data?.thread.version;
		const before = threadVersion === 3 ? earliestRunMessage?.run_id : earliestMessage?.id;

		if (threadVersion === 3 && !before) {
			this.#data.update((d) => ({
				...d,
				loading: false,
				canFetchMore: false
			}));
			return;
		}
		const response = await api.getThreadMessages(this.#fetcher, this.classId, this.threadId, {
			limit: currentData.limit,
			before: before || undefined
		});

		// Merge the new messages into the existing messages.
		this.#data.update((d) => {
			if (!d.data) {
				return d;
			}
			return {
				...d,
				data: {
					...d.data,
					ci_messages: [...(response.ci_messages || []), ...d.data.ci_messages],
					fs_messages: [...(response.fs_messages || []), ...d.data.fs_messages],
					ws_messages: [...(response.ws_messages || []), ...d.data.ws_messages],
					mcp_messages: [...(response.mcp_messages || []), ...(d.data.mcp_messages || [])],
					reasoning_messages: [
						...(response.reasoning_messages || []),
						...(d.data.reasoning_messages || [])
					],
					messages: [...response.messages, ...d.data.messages].sort(compareApiMessagesAsc)
				},
				limit: response.limit || d.limit,
				error: response.error ? { detail: response.error?.detail, wasSent: true } : null,
				loading: false,
				canFetchMore: response.has_more
			};
		});
	}

	async fetchCodeInterpreterResult(run_id: string, step_id: string) {
		this.#data.update((d) => ({ ...d, error: null, waiting: true }));
		try {
			const result = await api.getCIMessages(
				this.#fetcher,
				this.classId,
				this.threadId,
				run_id,
				step_id
			);
			if (result.error) {
				throw result.error;
			}
			this.#data.update((d) => {
				if (!d.data) {
					return d;
				}
				return {
					...d,
					data: {
						...d.data,
						ci_messages: [...result.ci_messages, ...d.data.ci_messages]
							.sort(compareApiMessagesAsc)
							.filter((message) => {
								return !(
									message.object === 'code_interpreter_call_placeholder' &&
									message.metadata &&
									message.metadata.step_id &&
									message.metadata.step_id === step_id
								);
							})
					},
					waiting: false
				};
			});
			return result;
		} catch (e) {
			this.#data.update((d) => ({
				...d,
				error: { detail: (e as Error).detail, wasSent: true },
				waiting: false
			}));
			throw e;
		}
	}

	/**
	 * Get the current thread data.
	 */
	get thread() {
		const currentData = get(this.#data);
		return currentData?.data?.thread;
	}

	/**
	 * Dismiss the current error.
	 */
	async dismissError() {
		this.#data.update((d) => ({ ...d, error: null }));
	}

	/**
	 * Send a new message to this thread.
	 */
	async postMessage(
		fromUserId: number,
		message: string,
		callback: ({ success, errorMessage, message_sent }: CallbackParams) => void,
		code_interpreter_file_ids?: string[],
		file_search_file_ids?: string[],
		vision_file_ids?: string[],
		vision_image_descriptions?: api.ImageProxy[],
		attachments?: api.ServerFile[]
	) {
		if (!message) {
			callback({
				success: false,
				errorMessage: 'Please enter a message before sending.',
				message_sent: false
			});
			this.#data.update((d) => ({
				...d,
				error: { detail: 'Please enter a message before sending.', wasSent: false }
			}));
			return;
		}

		const current = get(this.#data);

		if (current.waiting || current.submitting) {
			callback({
				success: false,
				errorMessage:
					'A response to the previous message is being generated. Please wait before sending a new message.',
				message_sent: false
			});
			this.#data.update((d) => ({
				...d,
				error: {
					detail:
						'A response to the previous message is being generated. Please wait before sending a new message.',
					wasSent: false
				}
			}));
			return;
		}

		// Generate an optimistic update for the UI
		const optimisticMsgId = `optimistic-${(Math.random() + 1).toString(36).substring(2)}`;
		const optimisticImageContent: api.MessageContentImageFile[] =
			vision_file_ids?.map((id) => ({ type: 'image_file', image_file: { file_id: id } })) ?? [];
		let visionImageDescriptionsString = '';
		if (vision_image_descriptions && vision_image_descriptions.length > 0) {
			const visionImageDescriptions =
				vision_image_descriptions?.map((proxy) => JSON.stringify(proxy)).join(',') || '';
			visionImageDescriptionsString = `\n{"Rd1IFKf5dl": [${visionImageDescriptions}]}`;
		}

		const optimisticMessageContent = message + visionImageDescriptionsString;
		const threadVersion = get(this.version);
		const currentState = get(this.#data);
		const optimisticOutputIndex =
			threadVersion === 3 ? this.#getNextOutputIndex(currentState) : undefined;
		const optimistic: api.OpenAIMessage = {
			id: optimisticMsgId,
			role: 'user',
			content: [
				{ type: 'text', text: { value: optimisticMessageContent, annotations: [] } },
				...optimisticImageContent
			],
			created_at: Math.floor(Date.now() / 1000),
			metadata: { user_id: fromUserId, is_current_user: true },
			assistant_id: '',
			file_search_file_ids: file_search_file_ids || [],
			code_interpreter_file_ids: code_interpreter_file_ids || [],
			vision_file_ids: vision_file_ids || [],
			run_id: null,
			object: 'thread.message',
			output_index: optimisticOutputIndex,
			attachments: (attachments || []).map((file) => ({ file_id: file.file_id, tools: [] }))
		};

		this.#data.update((d) => ({
			...d,
			error: null,
			optimistic: [...d.optimistic, optimistic],
			submitting: true,
			attachments: {
				...d.attachments,
				...attachments?.reduce((acc, file) => ({ ...acc, [file.file_id]: file }), {})
			}
		}));

		const chunks = await api.postMessage(this.#fetcher, this.classId, this.threadId, {
			message,
			file_search_file_ids,
			code_interpreter_file_ids,
			vision_file_ids,
			vision_image_descriptions,
			timezone: this.timezone
		});

		this.attachments = derived(this.#data, ($data) => {
			return $data?.attachments || {};
		});
		try {
			await this.#handleStreamChunks(chunks, callback);
			callback({ success: true, errorMessage: null, message_sent: true });
		} catch (e) {
			console.error('Error posting message', e);
			if (e instanceof api.PresendError || e instanceof api.RunActiveError) {
				this.#data.update((d) => ({
					...d,
					optimistic: d.optimistic.filter((msg) => msg.id !== optimisticMsgId),
					error: { detail: e.message, wasSent: false },
					attachments: Object.keys(d.attachments).reduce(
						(acc: Record<string, api.ServerFile>, key: string) => {
							if (!attachments?.find((file) => file.file_id === key)) {
								acc[key] = d.attachments[key];
							}
							return acc;
						},
						{} as Record<string, api.ServerFile>
					)
				}));
				if (e instanceof api.RunActiveError) {
					await this.#pollThread();
				}
			} else if (e instanceof api.StreamError) {
				this.#data.update((d) => ({
					...d,
					error: { detail: e.message, wasSent: true }
				}));
			} else {
				this.#data.update((d) => ({ ...d, error: { detail: (e as Error).detail, wasSent: true } }));
			}
		}
	}

	async #handleStreamChunks(
		chunks: AsyncIterable<api.ThreadStreamChunk>,
		callback: ({ success, errorMessage, message_sent }: CallbackParams) => void = () => {}
	) {
		this.#data.update((d) => ({
			...d,
			error: null,
			submitting: false,
			waiting: true
		}));

		try {
			for await (const chunk of chunks) {
				this.#handleStreamChunk(chunk, callback);
			}
		} catch (e) {
			console.error('Error handling stream chunks', e);
			this.#data.update((d) => ({
				...d,
				waiting: false
			}));
			throw e;
		} finally {
			this.#data.update((d) => ({
				...d,
				waiting: false
			}));
		}
	}

	#getHighestOutputIndex(state: ThreadManagerState | null) {
		if (!state) {
			return undefined;
		}
		const messages: api.OpenAIMessage[] = [
			...(state.data?.messages ?? []),
			...(state.data?.ci_messages ?? []),
			...(state.data?.fs_messages ?? []),
			...(state.data?.ws_messages ?? []),
			...(state.data?.mcp_messages ?? []),
			...(state.data?.reasoning_messages ?? []),
			...state.optimistic
		];
		const indices = messages
			.map((message) => message.output_index)
			.filter((index): index is number => typeof index === 'number');
		if (!indices.length) {
			return undefined;
		}
		return indices.reduce((max, index) => Math.max(max, index), -Infinity);
	}

	#getNextOutputIndex(state: ThreadManagerState | null) {
		const highest = this.#getHighestOutputIndex(state);
		if (highest === undefined) {
			return 0;
		}
		return highest + 1;
	}

	/**
	 * Set the thread data.
	 */
	setThreadData(data: BaseResponse & ThreadWithMeta) {
		this.#data.update((d) => {
			return { ...d, data };
		});
	}

	/**
	 * Handle a new chunk of data from a streaming response.
	 */
	#handleStreamChunk(
		chunk: api.ThreadStreamChunk,
		callback: ({ success, errorMessage, message_sent }: CallbackParams) => void = () => {}
	) {
		switch (chunk.type) {
			case 'message_created':
				this.#data.update((d) => {
					const version = get(this.version);
					const createdAt =
						version === 3 ? (chunk.message.created_at ?? Date.now() / 1000) : Date.now() / 1000;
					const outputIndex =
						version === 3 ? (chunk.message.output_index ?? this.#getNextOutputIndex(d)) : undefined;
					const message: api.OpenAIMessage = {
						...chunk.message,
						created_at: createdAt,
						output_index: outputIndex
					};
					return {
						...d,
						data: {
							...d.data!,
							messages: [...(d.data?.messages || []), message]
						}
					};
				});
				break;
			case 'message_delta':
				this.#appendDelta(chunk.delta);
				break;
			case 'done':
				break;
			case 'error':
				if (Array.isArray(chunk.detail)) {
					const errorMessage = chunk.detail.join('\n') || 'An unknown error occurred.';
					callback({ success: false, errorMessage, message_sent: true });
					throw new api.StreamError(errorMessage);
				}
				callback({
					success: false,
					errorMessage: chunk.detail || 'An unknown error occurred.',
					message_sent: true
				});
				throw new api.StreamError(chunk.detail || 'An unknown error occurred.');
			case 'presend_error':
				callback({
					success: false,
					errorMessage: chunk.detail || 'An unknown error occurred.',
					message_sent: false
				});
				throw new api.PresendError(chunk.detail || 'An unknown error occurred.');
			case 'run_active_error':
				callback({
					success: false,
					errorMessage: chunk.detail || 'An unknown error occurred.',
					message_sent: false
				});
				throw new api.RunActiveError(chunk.detail || 'An unknown error occurred.');
			case 'tool_call_created':
				this.#createToolCall(chunk.tool_call);
				this.#appendToolCallDelta(chunk.tool_call);
				break;
			case 'tool_call_delta':
				this.#appendToolCallDelta(chunk.delta);
				break;
			case 'reasoning_step_created':
				this.#createReasoningStep(chunk.reasoning_step);
				break;
			case 'reasoning_step_summary_part_added':
				this.#createReasoningSummaryPart(chunk.summary_part);
				break;
			case 'reasoning_summary_text_delta':
				this.#appendToReasoningSummaryPart(chunk);
				break;
			case 'reasoning_step_completed':
				this.#completeReasoningStep(chunk);
				break;
			default:
				console.warn('Unhandled chunk', chunk);
				break;
		}
	}

	#createReasoningStep(call: api.ThreadStreamReasoningStepCreatedChunk['reasoning_step']) {
		this.#data.update((d) => {
			const messages = d.data?.messages ?? [];
			if (!messages.length) {
				console.warn('createReasoningStep: Received a tool call without any messages.');
				return d;
			}
			const sortedMessages = [...messages].sort(compareApiMessagesDesc);
			const lastMessage = sortedMessages[0];
			if (!lastMessage) {
				console.warn('createReasoningStep: Received a tool call without a previous message.');
				return d;
			}

			if (
				lastMessage.role !== 'assistant' ||
				(lastMessage.run_id && call.run_id && lastMessage.run_id !== call.run_id)
			) {
				const version = get(this.version);
				const callOutputIndex =
					call.output_index ??
					(typeof call.index === 'number' ? call.index : undefined) ??
					(version === 3 ? this.#getNextOutputIndex(d) : undefined);
				d.data?.messages.push({
					role: 'assistant',
					content: [
						{
							step_id: String(call.id),
							type: 'reasoning',
							summary: (call.summary || []).map((part) => {
								return {
									id: part.summary_part_id,
									part_index: part.part_index,
									summary_text: part.summary_text
								};
							}),
							status: call.status ?? 'in_progress'
						}
					],
					created_at: Date.now() / 1000,
					id: `optimistic-${(Math.random() + 1).toString(36).substring(2)}`,
					assistant_id: '',
					metadata: {},
					file_search_file_ids: [],
					code_interpreter_file_ids: [],
					message_type: 'reasoning',
					object: 'thread.message',
					run_id: call.run_id || null,
					attachments: [],
					output_index: callOutputIndex
				});
			} else {
				lastMessage.content.push({
					step_id: String(call.id),
					type: 'reasoning',
					summary: (call.summary || []).map((part) => {
						return {
							id: part.summary_part_id,
							part_index: part.part_index,
							summary_text: part.summary_text
						};
					}),
					status: call.status ?? 'in_progress'
				});
			}

			return { ...d };
		});
	}

	#createReasoningSummaryPart(part: api.ReasoningStepSummaryPartChunk) {
		this.#data.update((d) => {
			const messages = d.data?.messages;
			if (!messages?.length) {
				console.warn('createReasoningSummaryPart: Received a tool call without any messages.');
				return d;
			}
			const sortedMessages = [...messages].sort(compareApiMessagesDesc);
			const messageWithReasoning = sortedMessages.find((message) =>
				message.content.some(
					(content) =>
						content.type === 'reasoning' && content.step_id === String(part.reasoning_step_id)
				)
			);
			if (!messageWithReasoning) {
				console.warn(
					'createReasoningSummaryPart: Received a reasoning summary part for a reasoning step that does not exist in the messages.'
				);
				return d;
			}

			const reasoningStep = messageWithReasoning.content.find((content) => {
				return content.type === 'reasoning' && content.step_id === String(part.reasoning_step_id);
			}) as api.ReasoningCallItem | undefined;

			if (!reasoningStep) {
				console.warn(
					'createReasoningSummaryPart: Received a reasoning summary part for a reasoning step that does not exist in the last message.'
				);
				return d;
			}

			reasoningStep.summary.push({
				id: part.summary_part_id,
				part_index: part.part_index,
				summary_text: part.summary_text
			});

			return { ...d };
		});
	}

	#appendToReasoningSummaryPart(call: api.ThreadStreamReasoningSummaryDeltaChunk) {
		this.#data.update((d) => {
			const messages = d.data?.messages;
			if (!messages?.length) {
				console.warn('appendToReasoningSummaryPart: Received a tool call without any messages.');
				return d;
			}
			const sortedMessages = [...messages].sort(compareApiMessagesDesc);
			const messageWithReasoning = sortedMessages.find((message) =>
				message.content.some(
					(content) =>
						content.type === 'reasoning' && content.step_id === String(call.reasoning_step_id)
				)
			);
			if (!messageWithReasoning) {
				console.warn(
					'appendToReasoningSummaryPart: Received a reasoning summary delta for a reasoning step that does not exist in the messages.'
				);
				return d;
			}

			const reasoningStep = messageWithReasoning.content.find((content) => {
				return content.type === 'reasoning' && content.step_id === String(call.reasoning_step_id);
			}) as api.ReasoningCallItem | undefined;

			if (!reasoningStep) {
				console.warn(
					'appendToReasoningSummaryPart: Received a reasoning summary part for a reasoning step that does not exist in the last message.'
				);
				return d;
			}

			const summaryPart = reasoningStep.summary.find((part) => part.id === call.summary_part_id);
			if (!summaryPart) {
				console.warn(
					'appendToReasoningSummaryPart: Received a reasoning summary delta for a summary part that does not exist.'
				);
				return d;
			}

			summaryPart.summary_text += call.delta;
			return { ...d };
		});
	}

	#completeReasoningStep(call: api.ThreadStreamReasoningStepCompletedChunk) {
		this.#data.update((d) => {
			const messages = d.data?.messages;
			if (!messages?.length) {
				console.warn('Received a tool call without any messages.');
				return d;
			}
			const sortedMessages = [...messages].sort(compareApiMessagesDesc);
			const messageWithReasoning = sortedMessages.find((message) =>
				message.content.some(
					(content) =>
						content.type === 'reasoning' && content.step_id === String(call.reasoning_step_id)
				)
			);
			if (!messageWithReasoning) {
				console.warn(
					'completeReasoningStep: Received a reasoning summary part for a reasoning step that does not exist in the messages.'
				);
				return d;
			}

			const reasoningStep = messageWithReasoning.content.find((content) => {
				return content.type === 'reasoning' && content.step_id === String(call.reasoning_step_id);
			}) as api.ReasoningCallItem | undefined;

			if (!reasoningStep) {
				console.warn(
					'completeReasoningStep: Received a reasoning summary part for a reasoning step that does not exist in the last message.'
				);
				return d;
			}

			reasoningStep.status = call.status;
			reasoningStep.thought_for = call.thought_for;
			return { ...d };
		});
	}

	/**
	 * Create a new tool call message.
	 */
	#createToolCall(call: api.ToolCallDelta) {
		this.#data.update((d) => {
			const messages = get(this.messages);
			if (!messages?.length) {
				console.warn('Received a tool call without any messages.');
				return d;
			}
			const sortedMessages = [...messages].sort(compareMessageDataDesc);
			const lastMessage = sortedMessages[0];
			if (!lastMessage) {
				console.warn('Received a tool call without a previous message.');
				return d;
			}

			if (
				lastMessage.data.role !== 'assistant' &&
				(call.type === 'code_interpreter' ||
					call.type === 'file_search' ||
					call.type === 'web_search' ||
					call.type === 'mcp_call' ||
					call.type === 'mcp_list_tools')
			) {
				const version = get(this.version);
				const callOutputIndex =
					call.output_index ??
					(typeof call.index === 'number' ? call.index : undefined) ??
					(version === 3 ? this.#getNextOutputIndex(d) : undefined);
				d.data?.messages.push({
					role: 'assistant',
					content: [],
					created_at: Date.now() / 1000,
					id: `optimistic-${(Math.random() + 1).toString(36).substring(2)}`,
					assistant_id: '',
					metadata: {},
					file_search_file_ids: [],
					code_interpreter_file_ids: [],
					object: 'thread.message',
					run_id: call.run_id || null,
					attachments: [],
					output_index: callOutputIndex
				});
			}
			return { ...d };
		});
	}

	#appendToolCallDelta(chunk: api.ToolCallDelta) {
		this.#data.update((d) => {
			const messages = d.data?.messages;
			if (!messages?.length) {
				console.warn('Received a tool call without any messages.');
				return d;
			}
			const sortedMessages = [...messages].sort(compareApiMessagesDesc);
			const lastMessage = sortedMessages[0];
			if (!lastMessage) {
				console.warn('Received a tool call without a previous message.');
				return d;
			}

			const lastChunk = lastMessage.content?.[lastMessage.content.length - 1];

			// Add a new message chunk with the new code
			if (chunk.type === 'code_interpreter') {
				if (chunk.code_interpreter.input) {
					if (!lastChunk || lastChunk.type !== 'code') {
						lastMessage.content.push({ type: 'code', code: chunk.code_interpreter.input });
					} else {
						// Merge code into existing chunk
						lastChunk.code += chunk.code_interpreter.input;
					}
				}

				// Add outputs to the last message
				if (chunk.code_interpreter.outputs) {
					for (const output of chunk.code_interpreter.outputs) {
						switch (output.type) {
							case 'image':
								lastMessage.content.push({
									type: 'code_output_image_file',
									image_file: output.image
								});
								break;
							case 'code_output_logs':
								lastMessage.content.push({
									type: 'code_output_logs',
									logs: output.logs
								});
								break;
							case 'code_output_image_url':
								lastMessage.content.push({
									type: 'code_output_image_url',
									url: output.url
								});
								break;
							default:
								console.warn('Unhandled tool call output', output);
								break;
						}
					}
				}
			} else if (chunk.type === 'file_search') {
				// Search across all assistant messages with the same run_id for the placeholder
				let placeholder: api.FileSearchCallItem | undefined;
				let targetMessage = lastMessage;

				for (const msg of sortedMessages) {
					if (msg.role === 'assistant' && (!chunk.run_id || msg.run_id === chunk.run_id)) {
						const found = msg.content.find(
							(c) => c.type === 'file_search_call' && c.step_id === chunk.id
						) as api.FileSearchCallItem | undefined;
						if (found) {
							placeholder = found;
							targetMessage = msg;
							break;
						}
					}
				}

				if (placeholder) {
					placeholder.queries = chunk.queries || [];
					placeholder.status = chunk.status;
				} else {
					targetMessage.content.push({
						type: 'file_search_call',
						step_id: chunk.id,
						status: chunk.status,
						queries: chunk.queries || []
					});
				}
			} else if (chunk.type === 'web_search') {
				// Search across all assistant messages with the same run_id for the placeholder
				let placeholder: api.WebSearchCallItem | undefined;
				let targetMessage = lastMessage;

				for (const msg of sortedMessages) {
					if (msg.role === 'assistant' && (!chunk.run_id || msg.run_id === chunk.run_id)) {
						const found = msg.content.find(
							(c) => c.type === 'web_search_call' && c.step_id === chunk.id
						) as api.WebSearchCallItem | undefined;
						if (found) {
							placeholder = found;
							targetMessage = msg;
							break;
						}
					}
				}

				if (placeholder) {
					placeholder.action = chunk.action || placeholder.action;
					placeholder.status = chunk.status;
				} else {
					targetMessage.content.push({
						type: 'web_search_call',
						step_id: chunk.id,
						action: chunk.action || null,
						status: chunk.status
					});
				}
			} else if (chunk.type === 'mcp_call') {
				// Search across all assistant messages with the same run_id for the placeholder
				// This handles the case where early chunks go to an optimistic message
				// but later chunks arrive after a real message is created
				let placeholder: api.MCPServerCallItem | undefined;
				let targetMessage = lastMessage;

				for (const msg of sortedMessages) {
					if (msg.role === 'assistant' && (!chunk.run_id || msg.run_id === chunk.run_id)) {
						const found = msg.content.find(
							(c) => c.type === 'mcp_server_call' && c.step_id === chunk.id
						) as api.MCPServerCallItem | undefined;
						if (found) {
							placeholder = found;
							targetMessage = msg;
							break;
						}
					}
				}

				const nextArguments =
					typeof chunk.arguments_delta === 'string'
						? `${placeholder?.arguments ?? ''}${chunk.arguments_delta}`
						: typeof chunk.arguments === 'string'
							? chunk.arguments
							: (placeholder?.arguments ?? null);

				if (placeholder) {
					placeholder.server_label = chunk.server_label ?? placeholder.server_label;
					placeholder.server_name = chunk.server_name ?? placeholder.server_name;
					placeholder.tool_name = chunk.name ?? placeholder.tool_name;
					placeholder.arguments = nextArguments ?? placeholder.arguments;
					if (chunk.output !== undefined) {
						placeholder.output = chunk.output;
					}
					if (chunk.error !== undefined) {
						placeholder.error = chunk.error;
					}
					if (chunk.status) {
						placeholder.status = chunk.status;
					}
				} else {
					targetMessage.content.push({
						type: 'mcp_server_call',
						step_id: chunk.id,
						server_label: chunk.server_label ?? '',
						server_name: chunk.server_name ?? null,
						tool_name: chunk.name ?? null,
						arguments: nextArguments,
						output: chunk.output ?? null,
						error: chunk.error ?? null,
						status: chunk.status ?? 'in_progress'
					});
				}
			} else if (chunk.type === 'mcp_list_tools') {
				// Search across all assistant messages with the same run_id for the placeholder
				// This handles the case where early chunks go to an optimistic message
				// but later chunks arrive after a real message is created
				let placeholder: api.MCPListToolsCallItem | undefined;
				let targetMessage = lastMessage;

				for (const msg of sortedMessages) {
					if (msg.role === 'assistant' && (!chunk.run_id || msg.run_id === chunk.run_id)) {
						const found = msg.content.find(
							(c) => c.type === 'mcp_list_tools_call' && c.step_id === chunk.id
						) as api.MCPListToolsCallItem | undefined;
						if (found) {
							placeholder = found;
							targetMessage = msg;
							break;
						}
					}
				}

				if (placeholder) {
					placeholder.server_label = chunk.server_label ?? placeholder.server_label;
					placeholder.server_name = chunk.server_name ?? placeholder.server_name;
					if (chunk.tools) {
						placeholder.tools = chunk.tools;
					}
					if (chunk.error !== undefined) {
						placeholder.error = chunk.error;
					}
					if (chunk.status) {
						placeholder.status = chunk.status;
					}
				} else {
					targetMessage.content.push({
						type: 'mcp_list_tools_call',
						step_id: chunk.id,
						server_label: chunk.server_label ?? '',
						server_name: chunk.server_name ?? null,
						tools: chunk.tools ?? [],
						error: chunk.error ?? null,
						status: chunk.status ?? 'in_progress'
					});
				}
			}
			return { ...d };
		});
	}

	/**
	 * Add a message delta into the current thread data.
	 */
	#appendDelta(chunk: api.OpenAIMessageDelta) {
		this.#data.update((d) => {
			const messages = d.data?.messages || [];
			const sortedMessages = [...messages].sort(compareApiMessagesDesc);
			const lastMessage = sortedMessages[0];
			if (!lastMessage) {
				console.warn('Received a message delta without a previous message.');
				return d;
			}

			for (const content of chunk.content) {
				this.#mergeContent(lastMessage.content, content);
			}

			return { ...d };
		});
	}

	/**
	 * Merge a message delta into the last message in the thread data.
	 */
	#mergeContent(contents: api.Content[], newContent: api.Content) {
		const lastContent = contents[contents.length - 1];
		if (!lastContent) {
			contents.push(newContent);
			return;
		}
		if (newContent.type === 'text') {
			if (lastContent.type === 'text') {
				// Ensure that the last content has a text value (non-null).
				if (!lastContent.text.value) {
					lastContent.text.value = '';
				}

				// Text content might be null, often when the delta only contains an annotation.
				if (newContent.text.value) {
					lastContent.text.value += newContent.text.value;
				}

				// Ensure that the last content has an annotations array.
				if (!lastContent.text.annotations) {
					lastContent.text.annotations = [];
				}

				// Merge any new annotations into the last content.
				if (newContent.text.annotations) {
					lastContent.text.annotations.push(...newContent.text.annotations);
				}

				return;
			} else {
				contents.push(newContent);
				return;
			}
		} else {
			contents.push(newContent);
		}
	}
}
