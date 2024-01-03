import {API_HOST, API_PROTO} from '$env/static/private';

export async function handleFetch({ request, fetch, event }) {
  // The server needs to redirect API requests to the API server, keeping
  // cookies intact along the way.
  const url = new URL(request.url);
  if (url.pathname.startsWith('/api/')) {
    url.protocol = API_PROTO;
    url.host = API_HOST;
    request = new Request(url.toString(), request);
    request.headers.set('cookie', event.request.headers.get('cookie'));
  }

  return fetch(request);
}
