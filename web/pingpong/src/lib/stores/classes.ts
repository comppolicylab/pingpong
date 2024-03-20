import { get, writable, derived, type Writable, type Readable } from 'svelte/store';
import * as api from '$lib/api';

/**
 * State for the classes manager.
 */
type ClassesManagerState = {
  loading: boolean;
  classes: api.Class[];
  error: api.Error | null;
  lastPage: boolean;
};

/**
 * Manages the index of classes.
 */
export class ClassesManager {
  #fetcher: api.Fetcher;
  #data: Writable<ClassesManagerState>;
  #defaultPageSize: number;

  /**
   * The current list of classes.
   */
  classes: Readable<api.Class[]>;

  /**
   * Any error that occurred while fetching classes.
   */
  error: Readable<api.Error | null>;

  /**
   * Whether classes are currently being loaded.
   */
  loading: Readable<boolean>;

  /**
   * Whether there are more classes to fetch.
   */
  canFetchMore: Readable<boolean>;

  /**
   * Create a new classes manager.
   */
  constructor(fetcher: api.Fetcher, defaultPageSize: number = 20) {
    this.#fetcher = fetcher;
    this.#defaultPageSize = defaultPageSize;
    this.#data = writable<ClassesManagerState>({
      loading: false,
      classes: [],
      error: null,
      lastPage: false
    });

    this.classes = derived(this.#data, ($data) => $data.classes);
    this.error = derived(this.#data, ($data) => $data.error);
    this.loading = derived(this.#data, ($data) => $data.loading);
    this.canFetchMore = derived(this.#data, ($data) => !$data.lastPage);
  }

  /**
   * Load the first page of classes.
   */
  async load(force: boolean = false, pageSize: number = this.#defaultPageSize) {
    const current = get(this.#data);
    if (current.loading) {
      return;
    }
    // Only load if we don't have any classes yet
    if (current.classes.length > 0 && !force) {
      return;
    }
    this.#data.update(($data) => ({ ...$data, error: null, classes: [], loading: true }));
    // TODO - pagination is not available in this API route yet
    const response = api.expandResponse(await api.getMyClasses(this.#fetcher));
    if (response.error) {
      this.#data.update(($data) => ({
        ...$data,
        loading: false,
        error: response.error,
        classes: [],
        lastPage: true
      }));
      return;
    } else {
      this.#data.update(($data) => ({
        ...$data,
        loading: false,
        classes: response.data.classes,
        lastPage: true
      }));
    }
  }

  /**
   * Load more classes.
   */
  async loadMore(pageSize: number = this.#defaultPageSize) {
    // TODO - pagination is not available in this API route yet
    return;
  }
}

/**
 * The global classes manager.
 */
let globalClassesManager: ClassesManager | null = null;

/**
 * Get the global classes manager.
 */
export function getClassesManager(fetcher: api.Fetcher): ClassesManager {
  if (!globalClassesManager) {
    globalClassesManager = new ClassesManager(fetcher);
  }
  return globalClassesManager;
}
