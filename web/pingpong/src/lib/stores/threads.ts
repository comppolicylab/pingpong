import {writable} from 'svelte/store';
import type {Writable} from 'svelte/store';
import * as api from '$lib/api';



class ThreadPoller {

  public classId: number;

  public threadId: number;

  public store: Writable<any>;

  private fetcher: api.Fetcher;

  private _getThreadPromise: Promise<void> | null = null;

  private _getLastRunPromise: Promise<void> | null = null;

  private _threadHash: string | null = null;

  constructor(fetcher: api.Fetcher, classId: number, threadId: number) {
    this.classId = classId;
    this.threadId = threadId;
    this.store = writable(null);
    this.fetcher = fetcher;
    this._getThread();
  }

  get loading() {
    return !!this._getThreadPromise || !!this._getLastRunPromise;
  }

  private async _getThread() {
    if (this._getThreadPromise) {
      await this._getThreadPromise;
      return;
    }

    this._getThreadPromise = this._getThreadReal();
    await this._getThreadPromise;
    this._getThreadPromise = null;
  }

  private async _getThreadRun() {
    if (this._getLastRunPromise) {
      await this._getLastRunPromise;
      return;
    }

    this._getLastRunPromise = this._pollLastRunReal();
    await this._getLastRunPromise;
    this._getLastRunPromise = null;
  }

  private async _getThreadReal() {
    const thread = await api.getThread(this.fetcher, this.classId, this.threadId);
    if (thread.hash !== this._threadHash) {
      this.store.set(thread);
      this._threadHash = thread.hash;
    }
  }

  private async _pollLastRunReal() {
    const timeout = 360 * 1000;
    const t0 = Date.now();

    while (Date.now() - t0 < timeout) {
      try {
        const lastRun = await api.getLastThreadRun(this.fetcher, this.classId, this.threadId);
        if (lastRun.$status >= 400) {
          break;
        }
        if (api.finished(lastRun.run)) {
          break;
        }
      } catch (e) {
        break;
      }
    }
    // TODO write last run to store
  }

  public async refresh(block: boolean = true) {
    if (block) {
      await this._getThreadRun();
    }
    await this._getThread();
  }

}

const _THREADS = new Map<number, ThreadPoller>();

export const threads = (fetcher: api.Fetcher, classId: number, threadId: number): ThreadPoller => {
  if (!_THREADS.has(threadId)) {
    _THREADS.set(threadId, new ThreadPoller(fetcher, classId, threadId));
  }

  const poller = _THREADS.get(threadId)!;
  return poller;
}
