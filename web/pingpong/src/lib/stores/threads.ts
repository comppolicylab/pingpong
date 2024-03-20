import { get, writable, derived, type Writable, type Readable } from 'svelte/store';
import * as api from '$lib/api';

/**
 * State for the threads manager.
 */
type ThreadsManagerState = {
  loading: boolean;
  threads: api.Thread[];
  error: api.Error | null;
  classId: number | null;
  lastPage: boolean;
};

/**
 * Sort threads by updated date, descending.
 */
const sortThreads = (threads: api.Thread[]): api.Thread[] => {
  return threads.sort((a, b) => (a.updated > b.updated ? -1 : 1));
};

/**
 * Manages the state of threads for a class.
 */
class ThreadsManager {
  #fetcher: api.Fetcher;
  #data: Writable<ThreadsManagerState>;
  #defaultPageSize: number;
  #reloadInterval: number;
  #lastLoaded: number;
  #timeout: ReturnType<typeof setTimeout> | null;

  /**
   * The current list of threads.
   *
   * This is not necessarily a complete list, only the threads loaded so far.
   */
  threads: Readable<api.Thread[]>;

  /**
   * Any error that occurred while fetching threads.
   */
  error: Readable<api.Error | null>;

  /**
   * Whether threads are currently being loaded.
   */
  loading: Readable<boolean>;

  /**
   * Whether there are more threads to fetch.
   */
  canFetchMore: Readable<boolean>;

  /**
   * Create a new threads manager.
   */
  constructor(fetcher: api.Fetcher, defaultPageSize: number = 20, reloadInterval: number = 60_000) {
    this.#fetcher = fetcher;
    this.#defaultPageSize = defaultPageSize;
    this.#reloadInterval = reloadInterval;
    this.#lastLoaded = 0;
    this.#timeout = null;
    this.#data = writable<ThreadsManagerState>({
      loading: false,
      threads: [],
      error: null,
      classId: null,
      lastPage: false
    });
    this.threads = derived(this.#data, ($d) => $d.threads);
    this.error = derived(this.#data, ($d) => $d.error);
    this.loading = derived(this.#data, ($d) => $d.loading);
    this.canFetchMore = derived(this.#data, ($d) => !$d.lastPage);
    this.#poll();
  }

  /**
   * Load the first page of threads for the given class.
   */
  async load(
    classId: number,
    force: boolean = false,
    pageSize: number = this.#defaultPageSize,
    background: boolean = false
  ) {
    const current = get(this.#data);
    if (current.loading) {
      return;
    }
    if (current.classId === classId && !force) {
      return;
    }
    this.#data.update((d) => ({
      ...d,
      error: null,
      threads: background ? d.threads : [],
      loading: !background,
      classId
    }));
    const response = await api.getClassThreads(this.#fetcher, classId, { limit: pageSize });
    this.#lastLoaded = Date.now();
    if (response.error) {
      this.#data.update((d) => {
        // If the class ID has changed, drop the update (race condition with another load call).
        if (d.classId !== classId) {
          return d;
        }
        return {
          ...d,
          loading: false,
          error: response.error,
          threads: [],
          lastPage: response.lastPage
        };
      });
      return;
    } else {
      this.#data.update((d) => {
        // If the class ID has changed, drop the update
        if (d.classId !== classId) {
          return d;
        }
        return {
          ...d,
          loading: false,
          error: null,
          threads: sortThreads(response.threads),
          lastPage: response.lastPage
        };
      });
    }
  }

  /**
   * Load another page of threads.
   */
  async loadMore(pageSize: number = this.#defaultPageSize) {
    const current = get(this.#data);
    if (current.loading || current.lastPage || !current.classId) {
      return;
    }
    this.#data.update((d) => ({ ...d, loading: true }));
    const lastThread = current.threads[current.threads.length - 1];
    const response = await api.getClassThreads(this.#fetcher, current.classId, {
      limit: pageSize,
      before: lastThread?.created
    });
    if (response.error) {
      this.#data.update((d) => {
        // If the class ID has changed, drop the update
        if (d.classId !== current.classId) {
          return d;
        }
        return { ...d, loading: false, error: response.error };
      });
      return;
    } else {
      this.#data.update((d) => {
        if (d.classId !== current.classId) {
          return d;
        }
        return {
          ...d,
          loading: false,
          error: null,
          threads: sortThreads([...d.threads, ...response.threads]),
          lastPage: response.lastPage
        };
      });
    }
  }

  /**
   * Add a new thread to the list.
   */
  add(thread: api.Thread) {
    this.#data.update((d) => ({ ...d, threads: sortThreads([thread, ...d.threads]) }));
  }

  /**
   * Poll for new threads.
   */
  async #poll() {
    if (this.#timeout) {
      clearTimeout(this.#timeout);
      this.#timeout = null;
    }
    const current = get(this.#data);
    const now = Date.now();
    let timeLeft = this.#reloadInterval - (now - this.#lastLoaded);
    if (timeLeft <= 0 && current.classId && !current.loading) {
      // Force a reload in the background if we're past the reload interval.
      await this.load(current.classId, true, this.#defaultPageSize, true);
      timeLeft = this.#reloadInterval;
    }

    // Schedule the next poll.
    this.#timeout = setTimeout(() => this.#poll(), timeLeft);
  }
}

/**
 * The global shared threads manager singleton.
 */
let globalThreadsManager: ThreadsManager | null = null;

/**
 * Get the global shared threads manager singleton.
 */
export const getThreadsManager = (fetcher: api.Fetcher): ThreadsManager => {
  if (!globalThreadsManager) {
    globalThreadsManager = new ThreadsManager(fetcher);
  }
  return globalThreadsManager;
};
