/**
 * Generate a key for the memoization cache.
 */
type KeyFn<T extends unknown[]> = (...args: T) => string;

/**
 * Reasonable key function to use for most inputs.
 */
const defaultKeyFn = (...args: unknown[]) => JSON.stringify(args);

/**
 * Wrap a function with a memoization cache.
 */
export const memoize = <S extends Array<unknown>, U, T extends (...args: S) => U>(
	fn: T,
	key: KeyFn<S> = defaultKeyFn
): T => {
	const cache = new Map<string, U>();
	return ((...args: Parameters<T>) => {
		const k = key(...args);
		if (!cache.has(k)) {
			cache.set(k, fn(...args));
		}
		return cache.get(k);
	}) as T;
};
