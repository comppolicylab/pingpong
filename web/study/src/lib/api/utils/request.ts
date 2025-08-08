import type { BaseData, Fetcher } from './types';
import { _qmethod, _bmethod } from './fetch';

/**
 * Query with GET.
 */
export const GET = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	path: string,
	data?: T
) => {
	return await _qmethod<T, R>(f, 'GET', path, data);
};

/**
 * Query with DELETE.
 */
export const DELETE = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	path: string,
	data?: T
) => {
	return await _qmethod<T, R>(f, 'DELETE', path, data);
};

/**
 * Query with POST.
 */
export const POST = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	path: string,
	data?: T
) => {
	return await _bmethod<T, R>(f, 'POST', path, data);
};

/**
 * Query with PUT.
 */
export const PUT = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	path: string,
	data?: T
) => {
	return await _bmethod<T, R>(f, 'PUT', path, data);
};

/**
 * Query with PATCH.
 */
export const PATCH = async <T extends BaseData, R extends BaseData>(
	f: Fetcher,
	path: string,
	data?: T
) => {
	return await _bmethod<T, R>(f, 'PATCH', path, data);
};
