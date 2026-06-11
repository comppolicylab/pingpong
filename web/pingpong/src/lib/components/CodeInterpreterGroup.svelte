<script context="module" lang="ts">
	import { writable, type Writable } from 'svelte/store';
	import { SvelteMap } from 'svelte/reactivity';

	type GroupState = {
		open: boolean;
		loading: boolean;
		fetching: boolean;
		requested: string[];
	};

	const groupStores = new SvelteMap<string, Writable<GroupState>>();

	const getGroupStore = (key: string) => {
		let store = groupStores.get(key);
		if (!store) {
			store = writable({ open: false, loading: false, fetching: false, requested: [] });
			groupStores.set(key, store);
		}
		return store;
	};
</script>

<script lang="ts">
	import { onDestroy } from 'svelte';
	import { slide } from 'svelte/transition';
	import { ChevronDownOutline, CodeOutline } from 'flowbite-svelte-icons';
	import { Spinner } from 'flowbite-svelte';
	import type * as api from '$lib/api';
	import CodeInterpreterCallItem from './CodeInterpreterCallItem.svelte';

	// Stable identity for this analysis block across placeholder/result replacement.
	export let stateKey: string;
	// The consecutive code-interpreter content items that make up a single analysis.
	export let items: api.Content[] = [];
	// Streaming while the assistant is still producing the analysis, done once persisted.
	export let streaming = false;
	// Force the group (and the steps inside it) open, e.g. for the print view.
	export let forceOpen = false;
	// Resolves a code-interpreter image output to a displayable URL.
	export let imageUrl: (item: api.MessageContentCodeOutputImageFile) => string | null;
	// Fetches the result for a placeholder step. Resolves once the result is loaded.
	export let onFetch: (run_id: string, step_id: string) => Promise<unknown>;

	let groupState = getGroupStore(stateKey);
	let previousStateKey: string | null = null;
	let previousOpen: boolean | null = null;
	let loadingDelayTimeout: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	const clearLoadingDelay = () => {
		if (loadingDelayTimeout) {
			clearTimeout(loadingDelayTimeout);
			loadingDelayTimeout = null;
		}
	};

	$: {
		if (previousStateKey && previousStateKey !== stateKey) {
			groupStores.delete(previousStateKey);
			previousOpen = null;
		}
		previousStateKey = stateKey;
	}
	$: groupState = getGroupStore(stateKey);
	$: open = forceOpen || $groupState.open;
	$: {
		if (forceOpen) {
			if (previousOpen === null) {
				previousOpen = $groupState.open;
			}
		} else if (previousOpen !== null) {
			const restoredOpen = previousOpen;
			groupState.update((state) => ({ ...state, open: restoredOpen }));
			previousOpen = null;
		}
	}

	$: placeholders = items.filter(
		(item): item is api.CodeInterpreterCallPlaceholder =>
			item.type === 'code_interpreter_call_placeholder'
	);
	$: hasPlaceholders = placeholders.length > 0;
	$: stepItems = items.filter((item) => item.type !== 'code_interpreter_call_placeholder');
	$: hasSteps = stepItems.length > 0;
	$: hasDropdown = hasPlaceholders || hasSteps;
	$: title = streaming ? 'Analyzing...' : 'Ran analysis';

	// Delay the spinner for quick cached responses; once visible, keep it long enough to read.
	const LOADING_INDICATOR_DELAY_MS = 150;
	const MIN_VISIBLE_LOADING_MS = 300;
	const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

	const contentKey = (item: api.Content, i: number) => {
		if (item.type === 'code_interpreter_call_placeholder') {
			return `${item.type}:${item.run_id}:${item.step_id}`;
		}
		if (item.type === 'code_output_image_file') {
			return `${item.type}:${item.run_id ?? ''}:${item.step_id ?? ''}:${item.image_file.file_id}:${item.source_message_id ?? i}`;
		}
		if (item.type === 'code_output_image_url') {
			return `${item.type}:${item.url}:${item.source_message_id ?? i}`;
		}
		if (item.type === 'code') {
			return `${item.type}:${item.source_message_id ?? ''}:${item.code}`;
		}
		if (item.type === 'code_output_logs') {
			return `${item.type}:${item.source_message_id ?? ''}:${item.logs}`;
		}
		return `${item.type}:${item.source_message_id ?? i}`;
	};

	const getItemLabel = (item: api.Content) => {
		switch (item.type) {
			case 'code':
				return 'Ran Code Interpreter code';
			case 'code_output_logs':
				return 'Returned Code Interpreter logs';
			case 'code_output_image_file':
			case 'code_output_image_url':
				return 'Generated image';
			default:
				return 'Ran analysis';
		}
	};

	const hasVisibleContent = (item: api.Content) => {
		switch (item.type) {
			case 'code':
				return item.code.trim().length > 0;
			case 'code_output_logs':
				return item.logs.trim().length > 0;
			case 'code_output_image_file':
				return item.image_file.file_id.trim().length > 0 && imageUrl(item) !== null;
			case 'code_output_image_url':
				return item.url.trim().length > 0;
			default:
				return false;
		}
	};

	const requestResults = async () => {
		if ($groupState.fetching) {
			return;
		}
		const pending = placeholders.filter(
			(placeholder) =>
				!$groupState.requested.includes(`${placeholder.run_id}:${placeholder.step_id}`)
		);
		if (pending.length === 0) {
			return;
		}
		const pendingKeys = pending.map(
			(placeholder) => `${placeholder.run_id}:${placeholder.step_id}`
		);
		const revealAfterLoad = !forceOpen;
		groupState.update((state) => ({
			...state,
			fetching: true,
			requested: Array.from(new Set([...state.requested, ...pendingKeys]))
		}));
		let loadingShownAt: number | null = null;
		loadingDelayTimeout = setTimeout(() => {
			loadingShownAt = Date.now();
			groupState.update((state) => ({ ...state, loading: true }));
			loadingDelayTimeout = null;
		}, LOADING_INDICATOR_DELAY_MS);
		try {
			await Promise.all(
				pending.map((placeholder) => onFetch(placeholder.run_id, placeholder.step_id))
			);
			if (revealAfterLoad) {
				// Reveal the results once they've loaded for a user-triggered load.
				groupState.update((state) => ({ ...state, open: true }));
			}
		} catch {
			// The parent surfaces the error; allow the user to retry the fetch.
			groupState.update((state) => ({
				...state,
				requested: state.requested.filter((key) => !pendingKeys.includes(key))
			}));
		} finally {
			clearLoadingDelay();
			if (loadingShownAt !== null) {
				const elapsed = Date.now() - loadingShownAt;
				await delay(Math.max(0, MIN_VISIBLE_LOADING_MS - elapsed));
			}
			if (!destroyed) {
				groupState.update((state) => ({ ...state, fetching: false, loading: false }));
			}
		}
	};

	const toggle = (event: MouseEvent) => {
		event.currentTarget?.dispatchEvent(
			new CustomEvent('pp:user-content-expansion', { bubbles: true })
		);
		// While results are still placeholders, a click kicks off the fetch and the
		// accordion opens itself once they arrive — rather than opening onto a spinner.
		if (hasPlaceholders) {
			requestResults();
			return;
		}
		if (!hasSteps) {
			return;
		}
		groupState.update((state) => ({ ...state, open: !state.open }));
	};

	// Eagerly fetch results when forced open (e.g. the print view) so they're visible.
	$: if (forceOpen && hasPlaceholders) {
		requestResults();
	}

	$: if (!hasPlaceholders && ($groupState.loading || $groupState.fetching)) {
		groupState.update((state) => ({
			...state,
			open: true,
			loading: false,
			fetching: false
		}));
	}

	onDestroy(() => {
		destroyed = true;
		clearLoadingDelay();
		groupStores.delete(stateKey);
	});
</script>

<div class="my-2">
	{#if hasDropdown}
		<button type="button" class="flex flex-row items-center gap-1" onclick={toggle}>
			<span class="inline-flex text-gray-600">
				<CodeOutline class="h-4 w-4" />
			</span>
			{#if streaming}
				<span class="shimmer text-sm font-medium">{title}</span>
			{:else}
				<span class="text-sm font-medium text-gray-600">{title}</span>
			{/if}
			{#if $groupState.loading}
				<Spinner color="gray" size="4" />
			{/if}
			<ChevronDownOutline class="text-gray-600 {open ? 'rotate-180 transform' : ''}" />
		</button>
	{:else}
		<div class="flex flex-row items-center gap-1">
			<span class="inline-flex text-gray-600">
				<CodeOutline class="h-4 w-4" />
			</span>
			<span class="text-sm font-medium text-gray-600">{title}</span>
		</div>
	{/if}

	{#if open && hasSteps}
		<div class="mt-2 ml-2 border-l border-gray-200 pl-4" transition:slide={{ duration: 250 }}>
			{#each stepItems as item, i (contentKey(item, i))}
				{#if item.type === 'code'}
					{#if hasVisibleContent(item)}
						<CodeInterpreterCallItem label={getItemLabel(item)} icon="code" {forceOpen}>
							<pre class="font-mono text-xs whitespace-pre-wrap text-gray-700">{item.code}</pre>
						</CodeInterpreterCallItem>
					{:else}
						<CodeInterpreterCallItem
							label={getItemLabel(item)}
							icon="code"
							forceOpen={false}
							hasContent={false}
						/>
					{/if}
				{:else if item.type === 'code_output_logs'}
					{#if hasVisibleContent(item)}
						<CodeInterpreterCallItem label={getItemLabel(item)} icon="logs" {forceOpen}>
							<pre class="font-mono text-xs whitespace-pre-wrap text-gray-700">{item.logs}</pre>
						</CodeInterpreterCallItem>
					{:else}
						<CodeInterpreterCallItem
							label={getItemLabel(item)}
							icon="logs"
							forceOpen={false}
							hasContent={false}
						/>
					{/if}
				{:else if item.type === 'code_output_image_file'}
					{#if hasVisibleContent(item)}
						<CodeInterpreterCallItem label={getItemLabel(item)} icon="image" {forceOpen}>
							{@const url = imageUrl(item)}
							{#if url}
								<img
									class="img-attachment m-auto"
									src={url}
									alt="Attachment generated by the assistant"
								/>
							{/if}
						</CodeInterpreterCallItem>
					{:else}
						<CodeInterpreterCallItem
							label={getItemLabel(item)}
							icon="image"
							forceOpen={false}
							hasContent={false}
						/>
					{/if}
				{:else if item.type === 'code_output_image_url'}
					{#if hasVisibleContent(item)}
						<CodeInterpreterCallItem label={getItemLabel(item)} icon="image" {forceOpen}>
							<img
								class="img-attachment m-auto"
								src={item.url}
								alt="Attachment generated by the assistant"
							/>
						</CodeInterpreterCallItem>
					{:else}
						<CodeInterpreterCallItem
							label={getItemLabel(item)}
							icon="image"
							forceOpen={false}
							hasContent={false}
						/>
					{/if}
				{/if}
			{/each}
		</div>
	{/if}
</div>
