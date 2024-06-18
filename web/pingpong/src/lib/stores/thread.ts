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
  error: Error | null;
  optimistic: api.OpenAIMessage[];
  limit: number;
  canFetchMore: boolean;
  loading: boolean;
  waiting: boolean;
  submitting: boolean;
  supportsFileSearch: boolean;
  supportsCodeInterpreter: boolean;
};

/**
 * A message in a thread.
 */
export type Message = {
  data: api.OpenAIMessage;
  error: Error | null;
  persisted: boolean;
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
   * The users in the thread.
   */
  users: Readable<api.UserPlaceholder[]>;

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
  error: Readable<Error | null>;

  #data: Writable<ThreadManagerState>;
  #fetcher: api.Fetcher;

  /**
   * Create a new thread manager.
   */
  constructor(
    fetcher: api.Fetcher,
    classId: number,
    threadId: number,
    threadData: BaseResponse & (ThreadWithMeta | Error)
  ) {
    const expanded = api.expandResponse(threadData);
    this.#fetcher = fetcher;
    this.classId = classId;
    this.threadId = threadId;
    this.#data = writable({
      data: expanded.data || null,
      error: expanded.error || null,
      limit: expanded.data?.limit || 20,
      canFetchMore: expanded.data ? expanded.data.messages.length == expanded.data.limit : false,
      supportsFileSearch: expanded.data?.thread?.tools_available?.includes('file_search') || false,
      supportsCodeInterpreter:
        expanded.data?.thread?.tools_available?.includes('code_interpreter') || false,
      optimistic: [],
      loading: false,
      waiting: false,
      submitting: false
    });

    this.#ensureRun(threadData);

    this.messages = derived(this.#data, ($data) => {
      if (!$data) {
        return [];
      }
      const realMessages = ($data.data?.messages || []).map((message) => ({
        data: message,
        error: null,
        persisted: true
      }));
      const codeInterpreterMessages = ($data.data?.code_interpreter_messages || []).map(
        (message) => ({
          data: message,
          error: null,
          persisted: true
        })
      );
      const optimisticMessages = $data.optimistic.map((message) => ({
        data: message,
        error: null,
        persisted: false
      }));
      // Sort messages together by created_at timestamp
      return realMessages
        .concat(codeInterpreterMessages)
        .concat(optimisticMessages)
        .sort((a, b) => a.data.created_at - b.data.created_at);
    });

    this.loading = derived(this.#data, ($data) => !!$data?.loading);

    this.waiting = derived(this.#data, ($data) => !!$data?.waiting);

    this.submitting = derived(this.#data, ($data) => !!$data?.submitting);

    this.assistantId = derived(this.#data, ($data) => $data?.data?.thread?.assistant_id || null);

    this.canFetchMore = derived(this.#data, ($data) => !!$data?.canFetchMore);

    this.published = derived(this.#data, ($data) => $data?.data?.thread?.private === false);

    this.error = derived(this.#data, ($data) => $data?.error || null);

    this.participants = derived(this.#data, ($data) => {
      if (!$data?.data) {
        return { user: {}, assistant: {} };
      }
      return $data.data.participants;
    });

    this.users = derived(this.#data, ($data) => $data?.data?.thread?.users || []);
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
    if (expanded.data.run) {
      if (!api.finished(expanded.data.run)) {
        await this.#pollThread();
        return;
      }
      // Otherwise, if the last run is finished, we can just display the results.
      return;
    }

    this.#data.update((d) => ({ ...d, submitting: true }));
    const chunks = await api.createThreadRun(this.#fetcher, this.classId, this.threadId);
    await this.#handleStreamChunks(chunks);
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
          error: expanded.error,
          waiting: false
        }));
        deferred.resolve();
        return;
      }

      if (Date.now() - t0 > timeout) {
        clearInterval(interval);
        this.#data.update((d) => ({
          ...d,
          error: { detail: 'The thread run took too long to complete.' },
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
      this.#data.update((d) => ({ ...d, error: e as Error, loading: false }));
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
      this.#data.update((d) => ({ ...d, error: e as Error, loading: false }));
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
      this.#data.update((d) => ({ ...d, error: e as Error, loading: false }));
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
    const earliestMessage = currentData.data?.messages.sort(
      (a, b) => a.created_at - b.created_at
    )[0];
    const response = await api.getThreadMessages(this.#fetcher, this.classId, this.threadId, {
      limit: currentData.limit,
      before: earliestMessage?.id
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
          code_interpreter_messages: [
            ...response.code_interpreter_messages,
            ...d.data.code_interpreter_messages
          ],
          messages: [...response.messages, ...d.data.messages].sort(
            (a, b) => a.created_at - b.created_at
          )
        },
        limit: response.limit || d.limit,
        error: response.error,
        loading: false,
        canFetchMore: !response.lastPage
      };
    });
  }

  async fetchCodeInterpreterResult(openai_thread_id: string, run_id: string, step_id: string) {
    this.#data.update((d) => ({ ...d, error: null, loading: true }));
    try {
      const result = await api.getCodeInterpreterResult(
        this.#fetcher,
        this.classId,
        this.threadId,
        openai_thread_id,
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
            code_interpreter_messages: [...result.messages, ...d.data.code_interpreter_messages]
              .sort((a, b) => a.created_at - b.created_at)
              .filter((message) => {
                return !(
                  message.object == 'thread.message.code_interpreter' &&
                  message.metadata &&
                  message.metadata.step_id &&
                  message.metadata.step_id == step_id
                );
              })
          },
          loading: false
        };
      });
      return result;
    } catch (e) {
      this.#data.update((d) => ({ ...d, error: e as Error, loading: false }));
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
   * Send a new message to this thread.
   */
  async postMessage(
    fromUserId: number,
    message: string,
    code_interpreter_file_ids?: string[],
    file_search_file_ids?: string[]
  ) {
    if (!message) {
      throw new Error('Please enter a message before sending.');
    }

    const current = get(this.#data);

    if (current.waiting || current.submitting) {
      throw new Error(
        'A response to the previous message is being generated. Please wait before sending a new message.'
      );
    }

    // Generate an optimistic update for the UI
    const optimisticMsgId = `optimistic-${(Math.random() + 1).toString(36).substring(2)}`;
    const optimistic: api.OpenAIMessage = {
      id: optimisticMsgId,
      role: 'user',
      content: [{ type: 'text', text: { value: message, annotations: [] } }],
      created_at: Date.now(),
      metadata: { user_id: fromUserId },
      assistant_id: '',
      thread_id: '',
      file_search_file_ids: file_search_file_ids || [],
      code_interpreter_file_ids: code_interpreter_file_ids || [],
      run_id: null,
      object: 'thread.message'
    };

    this.#data.update((d) => ({
      ...d,
      error: null,
      optimistic: [...d.optimistic, optimistic],
      submitting: true
    }));
    const chunks = await api.postMessage(this.#fetcher, this.classId, this.threadId, {
      message,
      file_search_file_ids,
      code_interpreter_file_ids
    });
    await this.#handleStreamChunks(chunks);
  }

  async #handleStreamChunks(chunks: AsyncIterable<api.ThreadStreamChunk>) {
    this.#data.update((d) => ({
      ...d,
      error: null,
      submitting: false,
      waiting: true
    }));

    try {
      for await (const chunk of chunks) {
        this.#handleStreamChunk(chunk);
      }
    } catch (e) {
      this.#data.update((d) => ({
        ...d,
        error: e as Error
      }));
    } finally {
      this.#data.update((d) => ({
        ...d,
        waiting: false
      }));
    }
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
  #handleStreamChunk(chunk: api.ThreadStreamChunk) {
    console.debug('Received chunk', chunk);
    switch (chunk.type) {
      case 'message_created':
        this.#data.update((d) => {
          return {
            ...d,
            data: {
              ...d.data!,
              messages: [
                ...(d.data?.messages || []),
                {
                  ...chunk.message,
                  // Note: make sure the message here has a timestamp that
                  // will be sequential to the optimistic messages.
                  // When the thread is reloaded, the real timestamps will be
                  // somewhat different.
                  created_at: Date.now()
                }
              ]
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
        throw new Error(chunk.detail || 'An unknown error occurred.');
      case 'tool_call_created':
        this.#createToolCall(chunk.tool_call);
        this.#appendToolCallDelta(chunk.tool_call);
        break;
      case 'tool_call_delta':
        this.#appendToolCallDelta(chunk.delta);
        break;
      default:
        console.warn('Unhandled chunk', chunk);
        break;
    }
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
      const sortedMessages = messages.sort((a, b) => b.data.created_at - a.data.created_at);
      const lastMessage = sortedMessages[0];
      if (!lastMessage) {
        console.warn('Received a tool call without a previous message.');
        return d;
      }

      if (lastMessage.data.role !== 'assistant' && call.type == 'code_interpreter') {
        d.data?.messages.push({
          role: 'assistant',
          content: [],
          created_at: Date.now(),
          id: `optimistic-${(Math.random() + 1).toString(36).substring(2)}`,
          assistant_id: '',
          thread_id: '',
          metadata: {},
          file_search_file_ids: [],
          code_interpreter_file_ids: [],
          object: 'thread.message',
          run_id: null
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
      const sortedMessages = messages.sort((a, b) => b.created_at - a.created_at);
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
              default:
                console.warn('Unhandled tool call output', output);
                break;
            }
          }
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
      const lastMessage = d.data?.messages[d.data!.messages.length - 1];
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
