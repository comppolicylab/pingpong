import { goto } from '$app/navigation';
import { page } from '$app/stores';
import { get } from 'svelte/store';

/**
 * Store a value in the URL search params
 */
export const updateSearch = (key: string, value: string) => {
  const $page = get(page);
  const searchParams = new URLSearchParams($page.url.searchParams.toString());
  searchParams.set(key, value);
  goto(`?${searchParams.toString()}`);
};

/**
 * Get the value of an input element from an event target.
 */
export const getValue = (el: EventTarget | null) => {
  if (!el) {
    return '';
  }
  if ((el as HTMLInputElement).value) {
    return (el as HTMLInputElement).value;
  }
  return '';
};
