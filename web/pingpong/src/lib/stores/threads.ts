import { writable, derived, get } from 'svelte/store';
import type { Writable, Readable } from 'svelte/store';
import * as api from '$lib/api';
import type { ThreadWithMeta, Error, BaseResponse } from '$lib/api';

export type ThreadData = {
  classId: number;
  threadId: number;
  data: (BaseResponse & ThreadWithMeta) | null;
  error: Error | null;
  optimistic: api.OpenAIMessage[];
  loading: boolean;
  waiting: boolean;
  submitting: boolean;
}

export type Message = {
  data: api.OpenAIMessage;
  error: Error | null;
  persisted: boolean;
}

class _Thread {
  public classId: number;

  public threadId: number;

  public messages: Readable<Message[]>;

  public loading: Readable<boolean>;

  public waiting: Readable<boolean>;

  public submitting: Readable<boolean>;

  public participants: Readable<api.ThreadParticipants>;

  public users: Readable<api.UserPlaceholder[]>;

  public published: Readable<boolean>;

  public assistantId: Readable<number | null>;

  public error: Readable<Error | null>;

  private data: Writable<ThreadData>;

  private _fetcher: api.Fetcher;

  constructor(fetcher: api.Fetcher, classId: number, threadId: number) {
    this._fetcher = fetcher;
    this.classId = classId;
    this.threadId = threadId;
    this.data = writable({
      classId,
      threadId,
      data: null,
      error: null,
      optimistic: [],
      loading: false,
      waiting: false,
      submitting: false,
    });

    this.messages = derived(this.data, ($data) => {
      if (!$data) {
        return [];
      }
      const realMessages = ($data.data?.messages || []).map((message) => ({ data: message, error: null, persisted: true }));
      const optimisticMessages = $data.optimistic.map((message) => ({ data: message, error: null, persisted: false }));
      // Sort messages together by created_at timestamp
      return realMessages.concat(optimisticMessages).sort((a, b) => a.data.created_at - b.data.created_at);
    });

    this.loading = derived(this.data, ($data) => !!$data?.loading);

    this.waiting = derived(this.data, ($data) => !!$data?.waiting);

    this.submitting = derived(this.data, ($data) => !!$data?.submitting);

    this.assistantId = derived(this.data, ($data) => $data?.data?.thread?.assistant_id || null);

    this.published = derived(this.data, ($data) => $data?.data?.thread?.private === false);

    this.error = derived(this.data, ($data) => $data?.error || null);

    this.participants = derived(this.data, ($data) => {
      if (!$data?.data) {
        return { user: {}, assistant: {} };
      }
      return $data.data.participants
    });

    this.users = derived(this.data, ($data) => $data?.data?.thread?.users || []);
  }

  async load() {
    this.data.update((d) => ({ ...d, loading: true }));
    const response = await api.getThread(this._fetcher, this.classId, this.threadId);
    const expanded = api.expandResponse(response);
    this.data.update((d) => {
      const newData = expanded.data || d.data || null;
      if (newData && d.data) {
        const allMessages = d.data.messages;
        if (expanded.data?.messages?.length) {
          allMessages.push(...expanded.data.messages);
        }
        newData.messages = allMessages;
      }
      return {
        classId: this.classId,
        threadId: this.threadId,
        data: newData,
        error: expanded.error,
        optimistic: d?.optimistic || [],
        loading: false,
        waiting: d.waiting,
        submitting: false,
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

    if (get(this.waiting)) {
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

    this.data.update((d) => ({
      ...d,
      optimistic: [...d.optimistic, optimistic],
      submitting: true,
    }));
    const chunks = await api.postMessage(fetch, this.classId, this.threadId, { message, file_ids });
    this.data.update((d) => ({
      ...d,
      submitting: false,
    }));

    try {
      for await (const chunk of chunks) {
        console.log("CHUNK", chunk);
        this.#handleStreamChunk(chunk);
      }
    } catch (e) {
      this.data.update((d) => ({
        ...d,
        error: e as Error,
      }));
    } finally {
      this.data.update((d) => ({
        ...d,
        waiting: false,
      }));
    }
  }

  _setThreadData(data: BaseResponse & ThreadWithMeta) {
    this.data.set({
      classId: this.classId,
      threadId: this.threadId,
      data: data,
      error: null,
      optimistic: [],
      loading: false,
      waiting: false,
      submitting: false,
    });
  }

  /**
   * Handle a new chunk of data from a streaming response.
   */
  #handleStreamChunk(chunk: api.ThreadStreamChunk) {
    switch (chunk.type) {
      case 'message_created':
        this.data.update((d) => ({
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
        }));
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
    this.data.update((d) => {
      const lastMessage = d.data?.messages[d.data!.messages.length - 1];
      if (!lastMessage) {
        return d;
      }

      for (const content of chunk.content) {
        this.#mergeContent(lastMessage.content, content);
      }

      return d;
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

const _THREADS = new Map<number, _Thread>();

/**
 * Get a thread by its class and thread ID.
 */
export const getThread = (fetcher: api.Fetcher, classId: number, threadId: number): _Thread => {
  if (!_THREADS.has(threadId)) {
    const thread = new _Thread(fetcher, classId, threadId);
    _THREADS.set(threadId, thread);
    thread.load();
  }

  return _THREADS.get(threadId)!;
};

/**
 * Create a new thread in a class.
 */
export const createThread = async (fetcher: api.Fetcher, classId: number, data: api.CreateThreadRequest): Promise<_Thread> => {
  const response = await api.createThread(fetcher, classId, data);
  const expanded = api.expandResponse(response);
  if (expanded.error) {
    throw expanded.error;
  }
  const thread = new _Thread(fetcher, classId, expanded.data.thread.id);
  thread._setThreadData(expanded.data);
  return thread;
}
