<script context="module" lang="ts">
	import { writable, type Writable } from 'svelte/store';
	import { SvelteMap } from 'svelte/reactivity';

	type GroupState = {
		open: boolean;
		loading: boolean;
		requested: string[];
	};

	const groupStores = new SvelteMap<string, Writable<GroupState>>();

	const getGroupStore = (key: string) => {
		let store = groupStores.get(key);
		if (!store) {
			store = writable({ open: false, loading: false, requested: [] });
			groupStores.set(key, store);
		}
		return store;
	};
</script>

<script lang="ts">
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
	// Resolves a code-interpreter image file id to a displayable URL.
	export let imageUrl: (fileId: string) => string;
	// Fetches the result for a placeholder step. Resolves once the result is loaded.
	export let onFetch: (run_id: string, step_id: string) => Promise<unknown>;

	let groupState = getGroupStore(stateKey);
	$: groupState = getGroupStore(stateKey);
	$: open = forceOpen || $groupState.open;

	$: placeholders = items.filter(
		(item): item is api.CodeInterpreterCallPlaceholder =>
			item.type === 'code_interpreter_call_placeholder'
	);
	$: hasPlaceholders = placeholders.length > 0;

	// Loading state for the in-flight fetch, surfaced next to the "Ran analysis" label.
	// Enforce a minimum visible duration so a near-instant (e.g. cached) response doesn't
	// flash the spinner and vanish, which reads as a jarring flicker.
	const MIN_LOADING_MS = 450;
	const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

	const requestResults = async () => {
		if ($groupState.loading) {
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
		groupState.update((state) => ({
			...state,
			loading: true,
			requested: Array.from(new Set([...state.requested, ...pendingKeys]))
		}));
		try {
			await Promise.all([
				delay(MIN_LOADING_MS),
				...pending.map((placeholder) => onFetch(placeholder.run_id, placeholder.step_id))
			]);
			// Reveal the results once they've loaded.
			groupState.update((state) => ({ ...state, open: true }));
		} catch {
			// The parent surfaces the error; allow the user to retry the fetch.
			groupState.update((state) => ({
				...state,
				requested: state.requested.filter((key) => !pendingKeys.includes(key))
			}));
		} finally {
			groupState.update((state) => ({ ...state, loading: false }));
		}
	};

	const toggle = () => {
		// While results are still placeholders, a click kicks off the fetch and the
		// accordion opens itself once they arrive — rather than opening onto a spinner.
		if (hasPlaceholders) {
			requestResults();
			return;
		}
		groupState.update((state) => ({ ...state, open: !state.open }));
	};

	// Eagerly fetch results when forced open (e.g. the print view) so they're visible.
	$: if (forceOpen && hasPlaceholders) {
		requestResults();
	}
</script>

<div class="my-2">
	<button type="button" class="flex flex-row items-center gap-1" onclick={toggle}>
		<span class="inline-flex text-gray-600">
			<CodeOutline class="h-4 w-4" />
		</span>
		{#if streaming}
			<span class="shimmer text-sm font-medium">Analyzing...</span>
		{:else}
			<span class="text-sm font-medium text-gray-600">Ran analysis</span>
		{/if}
		{#if $groupState.loading}
			<Spinner color="gray" size="4" />
		{/if}
		<ChevronDownOutline class="text-gray-600 {open ? 'rotate-180 transform' : ''}" />
	</button>

	{#if open}
		<div class="mt-2 ml-2 border-l border-gray-200 pl-4" transition:slide={{ duration: 250 }}>
			{#each items as item, i (i)}
				{#if item.type === 'code'}
					<CodeInterpreterCallItem label="Ran Code Interpreter code" icon="code" {forceOpen}>
						<pre class="font-mono text-xs whitespace-pre-wrap text-gray-700">{item.code}</pre>
					</CodeInterpreterCallItem>
				{:else if item.type === 'code_output_logs'}
					<CodeInterpreterCallItem label="Returned Code Interpreter logs" icon="logs" {forceOpen}>
						<pre class="font-mono text-xs whitespace-pre-wrap text-gray-700">{item.logs}</pre>
					</CodeInterpreterCallItem>
				{:else if item.type === 'code_output_image_file'}
					<CodeInterpreterCallItem label="Generated output image" icon="image" {forceOpen}>
						<img
							class="img-attachment m-auto"
							src={imageUrl(item.image_file.file_id)}
							alt="Attachment generated by the assistant"
						/>
					</CodeInterpreterCallItem>
				{:else if item.type === 'code_output_image_url'}
					<CodeInterpreterCallItem label="Generated output image" icon="image" {forceOpen}>
						<img
							class="img-attachment m-auto"
							src={item.url}
							alt="Attachment generated by the assistant"
						/>
					</CodeInterpreterCallItem>
				{/if}
			{/each}

			{#if hasPlaceholders && !$groupState.loading}
				<button
					type="button"
					class="my-2 text-sm font-medium text-gray-500 underline hover:text-gray-700"
					onclick={requestResults}
				>
					Load results
				</button>
			{/if}
		</div>
	{/if}
</div>
