/**
 * Convert any object to an error string.
 *
 * Usually we expect an `Error` object here.
 */
export const errorMessage = (error: unknown, fallback: string = 'unknown error'): string => {
  console.log('error', error);
  if (!error) {
    return fallback;
  } else if (error instanceof Error) {
    return error.message || `${error}` || fallback;
  } else if (typeof error === 'string') {
    return error || fallback;
  } else {
    return JSON.stringify(error);
  }
};
