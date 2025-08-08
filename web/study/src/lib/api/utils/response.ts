import type { BaseData, BaseResponse, Error, ValidationError } from './types';
import { isErrorResponse, isValidationError } from './error';

/**
 * Expand a response into its error and data components.
 */
export const expandResponse = <R extends BaseData>(
	r: BaseResponse & (Error | ValidationError | R)
) => {
	const $status = r.$status || 200;
	if (isValidationError(r)) {
		const detail = (r as ValidationError).detail;
		const error = detail
			.map((error) => {
				const location = error.loc.join(' -> '); // Join location array with arrow for readability
				return `Error at ${location}: ${error.msg}`;
			})
			.join('\n'); // Join all error messages with newlines
		return { $status, error: { detail: error } as Error, data: null };
	} else if (isErrorResponse(r)) {
		return { $status, error: r as Error, data: null };
	} else {
		return { $status, error: null, data: r as R };
	}
};

/**
 * Return response data or throw an error if one occurred.
 */
export const explodeResponse = <R extends BaseData>(
	r: BaseResponse & (Error | ValidationError | R)
) => {
	if (isValidationError(r)) {
		const detail = (r as ValidationError).detail;
		throw detail
			.map((error) => {
				const location = error.loc.join(' -> '); // Join location array with arrow for readability
				return `Error at ${location}: ${error.msg}`;
			})
			.join('\n'); // Join all error messages with newlines
	} else if (isErrorResponse(r)) {
		throw r;
	} else {
		return r as R;
	}
};
