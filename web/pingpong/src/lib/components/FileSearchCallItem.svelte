<script lang="ts">
	import { slide } from 'svelte/transition';
	import { ChevronDownOutline, FileSearchOutline } from 'flowbite-svelte-icons';
	import type { FileSearchCallItem } from '$lib/api';

	export let content: FileSearchCallItem;
	export let forceOpen = false;

	let open = false;
	let previousOpen: boolean | null = null;
	$: {
		if (forceOpen) {
			if (previousOpen === null) {
				previousOpen = open;
			}
			open = true;
		} else if (previousOpen !== null) {
			open = previousOpen;
			previousOpen = null;
		}
	}
	const handleClick = () => (open = !open);
</script>

<div class="my-3">
	{#if content.queries && content.queries.length > 0}
		<div class="flex items-center gap-2">
			<FileSearchOutline class="h-4 w-4 text-gray-600" />
			<button class="items-bottom flex flex-row" onclick={handleClick}>
				{#if content.status === 'completed'}
					<span class="text-sm font-medium text-gray-600"
						>Searched files {#if open}<span>for...</span>{/if}</span
					>
				{:else if content.status === 'failed'}
					<span class="text-sm font-medium text-yellow-600">File search failed</span>
				{:else if content.status === 'incomplete'}
					<span class="text-sm font-medium text-yellow-600">File search was canceled</span>
				{:else}
					<span class="shimmer text-sm font-medium">Searching files...</span>
				{/if}
				{#if open}
					<ChevronDownOutline class="rotate-180 transform text-gray-600" />
				{:else}
					<ChevronDownOutline class="text-gray-600" />
				{/if}
			</button>
		</div>
		{#if open}
			<div
				class="mt-1 ml-2 border-l border-gray-200 pl-4 text-sm font-light text-gray-600"
				transition:slide={{ duration: 250 }}
			>
				{#each content.queries as query, i (query)}
					<div class="py-0.5 leading-5" transition:slide={{ delay: i * 80, duration: 250 }}>
						{query}
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<div class="flex items-center gap-2">
			<FileSearchOutline class="h-4 w-4 text-gray-600" />
			<div class="items-bottom flex flex-row">
				{#if content.status === 'completed'}
					<span class="text-sm font-medium text-gray-600">Searched files</span>
				{:else if content.status === 'failed'}
					<span class="text-sm font-medium text-yellow-600">File search failed</span>
				{:else if content.status === 'incomplete'}
					<span class="text-sm font-medium text-yellow-600">File search was canceled</span>
				{:else}
					<span class="shimmer text-sm font-medium">Searching files...</span>
				{/if}
			</div>
		</div>
	{/if}
</div>
