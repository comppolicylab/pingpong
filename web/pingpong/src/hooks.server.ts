import type { HandleFetch, Handle } from '@sveltejs/kit';
import { sequence } from '@sveltejs/kit/hooks';
import * as Sentry from '@sentry/sveltekit';
import { API_HOST, API_PROTO } from '$env/static/private';

// Instantiate Sentry if a DSN is provided.
const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN;
if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    tracesSampleRate: 1
  });
}

/**
 * Override default route handler to provide a health check indicator.
 */
export const handleHealthCheck: Handle = async ({ event, resolve }) => {
  if (event.url.pathname === '/health') {
    return new Response('ok');
  }

  return await resolve(event);
};

/**
 * Override default fetcher to redirect API requests to the API server.
 */
export const handleFetch: HandleFetch = async ({ request, fetch, event }) => {
  // The server needs to redirect API requests to the API server, keeping
  // cookies intact along the way.
  const url = new URL(request.url);
  if (url.pathname.startsWith('/api/')) {
    url.protocol = API_PROTO;
    url.host = API_HOST;
    request = new Request(url.toString(), request);
    const cookie = event.request.headers.get('cookie');
    if (cookie) {
      request.headers.set('cookie', cookie);
    }
  }

  return fetch(request);
};

export const handleError = Sentry.handleErrorWithSentry();

export const handle = sequence(handleHealthCheck, Sentry.sentryHandle());
