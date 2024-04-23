import { writable } from 'svelte/store';

/**
 * Store for the app menu open state.
 */
export const appMenuOpen = writable(false);
