export class Deferred<T> {
  #resolver: (value?: T | PromiseLike<T>) => void = () => {};
  #rejecter: (reason?: unknown) => void = () => {};
  #promise: Promise<T | void>;

  constructor() {
    this.#promise = new Promise<T | void>((resolve, reject) => {
      this.#resolver = resolve;
      this.#rejecter = reject;
    });
  }

  resolve(value?: T | PromiseLike<T>) {
    this.#resolver(value);
  }

  reject(reason?: unknown) {
    this.#rejecter(reason);
  }

  get promise() {
    return this.#promise;
  }

  get [Symbol.toStringTag]() {
    return 'Deferred';
  }
}
