/**
 * Convert any object to an error string.
 *
 * Usually we expect an `Error` object here.
 */

import * as api from '$lib/api';

export const errorMessage = (error: unknown, fallback: string = 'unknown error'): string => {
  if (!error) {
    return fallback;
  } else if (error instanceof Error) {
    return error.message || `${error}` || fallback;
  } else if (api.isErrorResponse(error)) {
    return error.detail || `${error}` || fallback;
  } else if (api.isValidationError(error)) {
    if (!error.detail) {
      return `${error}` || fallback;
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
