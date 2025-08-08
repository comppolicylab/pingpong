/**
 * HTTP methods.
 */
export type Method = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';

/**
 * General fetcher type.
 */
export type Fetcher = typeof fetch;

/**
 * Base data type for all API responses.
 */
export type BaseData = Record<string, unknown>;

/**
 * Base Response type for all API responses.
 */
export type BaseResponse = {
	$status: number;
	detail?: string;
};

/**
 * Error data.
 */
export type Error = {
	detail?: string;
};

export type ValidationError = {
	detail: {
		loc: string[];
		msg: string;
		type: string;
	}[];
};

/**
 * Error response. The $status will be >= 400.
 */
export type ErrorResponse = Error & BaseResponse;
export type ValidationErrorResponse = ValidationError & BaseResponse;

/**
 * Generic response returned by some API endpoints.
 */
export type GenericStatus = {
	status: string;
};
