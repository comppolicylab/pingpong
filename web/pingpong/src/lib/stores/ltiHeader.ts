import { writable } from 'svelte/store';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const ltiHeaderComponent = writable<any>(null);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const ltiHeaderProps = writable<Record<string, any>>({});
