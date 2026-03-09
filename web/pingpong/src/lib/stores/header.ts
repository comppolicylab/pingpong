import type { ComponentProps } from 'svelte';
import { writable } from 'svelte/store';
import type ThreadHeader from '$lib/components/ThreadHeader.svelte';
import type NonGroupHeader from '$lib/components/NonGroupHeader.svelte';

export type ThreadHeaderProps = ComponentProps<ThreadHeader>;
export type NonGroupHeaderProps = ComponentProps<NonGroupHeader>;

export type HeaderState =
	| { kind: 'thread'; props: ThreadHeaderProps }
	| { kind: 'nongroup'; props: NonGroupHeaderProps }
	| { kind: 'none' };

export const headerState = writable<HeaderState>({ kind: 'none' });
