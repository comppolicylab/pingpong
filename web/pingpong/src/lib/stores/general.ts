import type { AssistantModels } from '$lib/api';
import { writable } from 'svelte/store';

/**
 * Store for the app menu open state.
 */
export const appMenuOpen = writable(false);

/**
 * Store for a big loading indicator over the main page.
 *
 * TODO(jnu): there could be race conditions with this shared store;
 * consider using a fancier counter-based system instead.
 */
export const loading = writable(false);

export const loadingMessage = writable('');

export const isFirefox = writable(false);

export const anonymousSessionToken = writable<string | null>(null);

export function detectBrowser() {
  if (typeof window !== 'undefined') {
    isFirefox.set(navigator.userAgent.toLowerCase().includes('firefox'));
  }
}

export const modelsPromptsStore = writable<Record<number, AssistantModels>>({});
