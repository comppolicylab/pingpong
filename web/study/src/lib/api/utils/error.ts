import type {
	BaseResponse,
	ErrorResponse,
	ValidationError,
	ValidationErrorResponse
} from './types';

/**
 * Check whether a response is an error.
 */
export const isErrorResponse = (r: unknown): r is ErrorResponse => {
	return !!r && Object.hasOwn(r, '$status') && (r as BaseResponse).$status >= 400;
};

export const isValidationError = (r: unknown): r is ValidationErrorResponse => {
	if (!!r && Object.hasOwn(r, '$status') && (r as BaseResponse).$status === 422) {
		const detail = (r as ValidationError).detail;
		// Check if the detail is an array and contains objects with "type" and "msg" keys.
		if (Array.isArray(detail) && detail.every((item) => item.type && item.msg)) {
			return true;
		}
	}
	return false;
};
