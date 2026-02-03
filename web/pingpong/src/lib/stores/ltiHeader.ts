import type { ComponentProps, ComponentType } from 'svelte';
import { writable } from 'svelte/store';
import type ThreadHeader from '$lib/components/ThreadHeader.svelte';
import type NonGroupHeader from '$lib/components/NonGroupHeader.svelte';

type ThreadHeaderProps = ComponentProps<ThreadHeader>;
type NonGroupHeaderProps = ComponentProps<NonGroupHeader>;

export type LtiHeaderProps = ThreadHeaderProps | NonGroupHeaderProps | Record<string, never>;

export type LtiHeaderComponent = ComponentType<ThreadHeader> | ComponentType<NonGroupHeader> | null;

export const ltiHeaderComponent = writable<LtiHeaderComponent>(null);
export const ltiHeaderProps = writable<LtiHeaderProps>({});
