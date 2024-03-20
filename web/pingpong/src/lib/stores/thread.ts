import { writable, derived, get } from 'svelte/store';
import type { Writable, Readable } from 'svelte/store';
import * as api from '$lib/api';
import type { ThreadWithMeta, Error, BaseResponse } from '$lib/api';

/**
 * State for the thread manager.
 */
export type ThreadManagerState = {
  classId: number;
  threadId: number;
  data: (BaseResponse & ThreadWithMeta) | null;
  error: Error | null;
  optimistic: api.OpenAIMessage[];
  loading: boolean;
  waiting: boolean;
  submitting: boolean;
}

/**
 * A message in a thread.
 */
export type Message = {
  data: api.OpenAIMessage;
  error: Error | null;
  persisted: boolean;
}

/**
 * Manager for a single conversation thread.
 */
class ThreadManager {
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
   * Any error that occurred while fetching the thread.
   */
  error: Readable<Error | null>;

  #data: Writable<ThreadManagerState>;
  #fetcher: api.Fetcher;

  /**
   * Create a new thread manager.
   */
  constructor(fetcher: api.Fetcher, classId: number, threadId: number) {
    this.#fetcher = fetcher;
    this.classId = classId;
    this.threadId = threadId;
    this.#data = writable({
      classId,
      threadId,
      data: null,
      error: null,
      optimistic: [],
      loading: false,
      waiting: false,
      submitting: false,
    });

    this.messages = derived(this.#data, ($data) => {
      if (!$data) {
        return [];
      }
      const realMessages = ($data.data?.messages || []).map((message) => ({ data: message, error: null, persisted: true }));
      const optimisticMessages = $data.optimistic.map((message) => ({ data: message, error: null, persisted: false }));
      // Sort messages together by created_at timestamp
      return realMessages.concat(optimisticMessages).sort((a, b) => a.data.created_at - b.data.created_at);
    });

    this.loading = derived(this.#data, ($data) => !!$data?.loading);

    this.waiting = derived(this.#data, ($data) => !!$data?.waiting);

    this.submitting = derived(this.#data, ($data) => !!$data?.submitting);

    this.assistantId = derived(this.#data, ($data) => $data?.data?.thread?.assistant_id || null);

    this.published = derived(this.#data, ($data) => $data?.data?.thread?.private === false);

    this.error = derived(this.#data, ($data) => $data?.error || null);

    this.participants = derived(this.#data, ($data) => {
      if (!$data?.data) {
        return { user: {}, assistant: {} };
      }
      return $data.data.participants
    });

    this.users = derived(this.#data, ($data) => $data?.data?.thread?.users || []);
  }

  /**
   * Get the current thread data.
   */
  get thread() {
    const currentData = get(this.#data);
    return currentData?.data?.thread;
  }

  /**
   * Load the thread data.
   */
  async load() {
    this.#data.update((d) => ({ ...d, loading: true }));
    const response = await api.getThread(this.#fetcher, this.classId, this.threadId);
    const expanded = api.expandResponse(response);
    // TODO - if a thread run is in progress, subscribe to it.
    console.log("Expanded thread", expanded);
    this.#data.update((d) => {
      const newData = expanded.data;
      if (d.data && newData) {
        newData.messages = [...(d.data?.messages || []), ...(expanded.data?.messages || [])];
      }
      return {
        ...d,
        data: newData,
        error: expanded.error,
        loading: false,
      };
    });
  }

  /**
   * Send a new message to this thread.
   */
  async postMessage(fromUserId: number, message: string, file_ids?: string[]) {
    if (!message) {
      throw new Error('Please enter a message before sending.');
    }

    const current = get(this.#data);

    if (current.waiting || current.submitting) {
      throw new Error('A response to the previous message is being generated. Please wait before sending a new message.');
    }

    // Generate an optimistic update for the UI
    const optimisticMsgId = `optimistic-${(Math.random() + 1).toString(36).substring(2)}`;
    const optimistic: api.OpenAIMessage = {
      id: optimisticMsgId,
      role: 'user',
      content: [{ type: 'text', text: { value: message, annotations: [] } }],
      created_at: Date.now(),
      metadata: { user_id: fromUserId },
      assistant_id: "",
      thread_id: "",
      file_ids: file_ids || [],
      run_id: null,
      object: "thread.message",
    };

    this.#data.update((d) => ({
      ...d,
      optimistic: [...d.optimistic, optimistic],
      submitting: true,
    }));
    const chunks = await api.postMessage(fetch, this.classId, this.threadId, { message, file_ids });
    this.#data.update((d) => ({
      ...d,
      submitting: false,
      waiting: true,
    }));

    try {
      for await (const chunk of chunks) {
        this.#handleStreamChunk(chunk);
      }
    } catch (e) {
      this.#data.update((d) => ({
        ...d,
        error: e as Error,
      }));
    } finally {
      this.#data.update((d) => ({
        ...d,
        waiting: false,
      }));
    }
  }

  /**
   * Set the thread data.
   */
  setThreadData(data: BaseResponse & ThreadWithMeta) {
    this.#data.update(d => {
      return {...d, data};
    });
  }

  /**
   * Handle a new chunk of data from a streaming response.
   */
  #handleStreamChunk(chunk: api.ThreadStreamChunk) {
    switch (chunk.type) {
      case 'message_created':
        this.#data.update((d) => {
          return {
            ...d,
            data: {
              ...d.data!,
              messages: [...(d.data?.messages || []), {
                ...chunk.message,
                // Note: make sure the message here has a timestamp that
                // will be sequential to the optimistic messages.
                // When the thread is reloaded, the real timestamps will be
                // somewhat different.
                created_at: Date.now(),
              }],
            }
          };
        });
        break;
      case 'message_delta':
        this.#appendDelta(chunk.delta);
        break
      case 'done':
        break;
      case 'error':
        throw new Error(chunk.detail || "An unknown error occurred.");
      default:
        console.warn("Unhandled chunk", chunk);
        break;
    }
  }

  /**
   * Add a message delta into the current thread data.
   */
  #appendDelta(chunk: api.OpenAIMessageDelta) {
    this.#data.update((d) => {
      const lastMessage = d.data?.messages[d.data!.messages.length - 1];
      if (!lastMessage) {
        console.warn("Received a message delta without a previous message.");
        return d;
      }

      for (const content of chunk.content) {
        this.#mergeContent(lastMessage.content, content);
      }

      return {...d};
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
    if (newContent.type === "text") {
      if (lastContent.type === "text") {
        lastContent.text.value += newContent.text.value;
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

/**
 * Cache of thread managers.
 */
const _THREADS = new Map<number, ThreadManager>();

/**
 * Get a thread by its class and thread ID.
 */
export const getThread = (fetcher: api.Fetcher, classId: number, threadId: number): ThreadManager => {
  if (!_THREADS.has(threadId)) {
    const thread = new ThreadManager(fetcher, classId, threadId);
    _THREADS.set(threadId, thread);
    thread.load();
  }

  return _THREADS.get(threadId)!;
};

/**
 * Create a new thread in a class.
 */
export const createThread = async (fetcher: api.Fetcher, classId: number, data: api.CreateThreadRequest): Promise<ThreadManager> => {
  const response = await api.createThread(fetcher, classId, data);
  const expanded = api.expandResponse(response);
  if (expanded.error) {
    throw expanded.error;
  }
  const thread = new ThreadManager(fetcher, classId, expanded.data.thread.id);
  thread.setThreadData(expanded.data);
  _THREADS.set(expanded.data.thread.id, thread);
  return thread;
}
