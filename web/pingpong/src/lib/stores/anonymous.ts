import { get, writable } from 'svelte/store';

export const anonymousSessionToken = writable<string | null>(null);
export const anonymousShareToken = writable<string | null>(null);

export const setAnonymousSessionToken = (token: string | null) => {
  anonymousSessionToken.set(token);
};

export const resetAnonymousSessionToken = () => {
  anonymousSessionToken.set(null);
};

export const hasAnonymousSessionToken = () => {
  return get(anonymousSessionToken) !== null;
};

export const getAnonymousSessionToken = () => {
  return get(anonymousSessionToken);
};

export const setAnonymousShareToken = (token: string | null) => {
  anonymousShareToken.set(token);
};

export const resetAnonymousShareToken = () => {
  anonymousShareToken.set(null);
};

export const hasAnonymousShareToken = () => {
  return get(anonymousShareToken) !== null;
};

export const getAnonymousShareToken = () => {
  return get(anonymousShareToken);
};
