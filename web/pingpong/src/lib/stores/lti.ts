import { get, writable } from 'svelte/store';

export const LTISessionToken = writable<string | null>(null);

export const setLTISessionToken = (token: string | null) => {
  LTISessionToken.set(token);
};

export const resetLTISessionToken = () => {
  LTISessionToken.set(null);
};

export const hasLTISessionToken = () => {
  return get(LTISessionToken) !== null;
};

export const getLTISessionToken = () => {
  return get(LTISessionToken);
};
