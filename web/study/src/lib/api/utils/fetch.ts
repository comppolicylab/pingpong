import type { BaseData, BaseResponse, Error, ValidationError, Method, Fetcher } from './types';

/**
 * Join URL parts with a slash.
 */
export const join = (...parts: string[]) => {
	let full = '';
	for (const part of parts) {
		if (full) {
			if (!full.endsWith('/')) {
				full += '/';
			}
			full += part.replace(/^\/+/, '');
		} else {
			full = part;
		}
	}
	return full;
};

/**
 * Get full API route.
 */
export const fullPath = (path: string) => {
	return join('/api/study/', path);
};

/**
 * Common fetch method.
 */
const _fetch = async (
	f: Fetcher,
	method: Method,
	path: string,
	headers?: Record<string, string>,
	body?: string | FormData
) => {
	const full = fullPath(path);
	return f(full, {
		method,
		headers,
		body,
		credentials: 'include',
		mode: 'cors'
	});
};

/**
 * Common fetch method returning a JSON response.
 */
const _fetchJSON = async <R extends BaseData>(
	f: Fetcher,
	method: Method,
	path: string,
	headers?: Record<string, string>,
	body?: string | FormData
): Promise<(R | Error | ValidationError) & BaseResponse> => {
	const res = await _fetch(f, method, path, headers, body);

	let data: BaseData = {};

	try {
		data = await res.json();
	} catch {
		// Do nothing
	}

	return { $status: res.status, ...data } as (R | Error) & BaseResponse;
};

/**
 * Method that passes data in the query string.
 */
export const _qmethod = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	method: 'GET' | 'DELETE',
	path: string,
	data?: T
) => {
	// Treat args the same as when passed in the body.
	// Specifically, we want to remove "undefined" values.
	const filtered = data && (JSON.parse(JSON.stringify(data)) as Record<string, string>);
	const params = new URLSearchParams(filtered);
	path = `${path}?${params}`;
	return await _fetchJSON<R>(f, method, path);
};

/**
 * Method that passes data in the body.
 */
export const _bmethod = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	method: 'POST' | 'PUT' | 'PATCH',
	path: string,
	data?: T
) => {
	const body = JSON.stringify(data);
	const headers = { 'Content-Type': 'application/json' };
	return await _fetchJSON<R>(f, method, path, headers, body);
};
