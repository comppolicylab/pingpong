<script lang="ts">
	import ThreadHeader from '$lib/components/ThreadHeader.svelte';
	import { page } from '$app/stores';
	import { onMount, setContext } from 'svelte';
	import { writable } from 'svelte/store';

	let { data, children } = $props();

	let headerEl: HTMLDivElement | undefined = $state();
	const headerHeightStore = writable(0);

	onMount(() => {
		headerHeightStore.set(headerEl?.offsetHeight ?? 0);
	});

	setContext('headerHeightStore', headerHeightStore);

	// Figure out if we're on the assistant page.
	// When we are, we want to show the "Manage Class" link.
	// For every other page, we show the "View Class Page" link.
	let isOnClassPage = $derived($page.url.pathname === `/group/${data.class?.id}/assistant`);
</script>

<div class="relative flex h-full w-full flex-col">
	{#if !(data.isSharedAssistantPage || data.isSharedThreadPage)}
		<div bind:this={headerEl} class="print-hidden">
			<ThreadHeader
				current={data.class}
				classes={data.classes}
				canManage={data.canManage}
				{isOnClassPage}
				isSharedPage={data.isSharedAssistantPage || data.isSharedThreadPage}
			/>
		</div>
	{/if}
	{@render children?.()}
</div>

<style>
	@media print {
		.print-hidden {
			display: none !important;
		}
	}
</style>
