/**
 * Convert any object to an error string.
 *
 * Usually we expect an `Error` object here.
 */

import { isValidationError, isErrorResponse } from '$lib/api';

export const errorMessage = (error: unknown, fallback: string = 'unknown error'): string => {
	console.error(error);
	if (!error) {
		return fallback;
	} else if (error instanceof Error) {
		return error.message || fallback;
	} else if (isErrorResponse(error)) {
		return error.detail || fallback;
	} else if (isValidationError(error)) {
		if (!error.detail) {
			return fallback;
		} else {
			return error.detail
				.map((error) => {
					const location = error.loc.join(' -> ');
					return `Error at ${location}: ${error.msg}`;
				})
				.join('\n');
		}
	} else if (typeof error === 'string') {
		return error || fallback;
	} else {
		return JSON.stringify(error);
	}
};
