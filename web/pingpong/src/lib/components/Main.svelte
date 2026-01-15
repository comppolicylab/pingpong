<script lang="ts">
	import { appMenuOpen } from '$lib/stores/general';
	import { navigating } from '$app/stores';
	import { Pulse } from 'svelte-loading-spinners';
	import { blur } from 'svelte/transition';
	import { loading, loadingMessage } from '$lib/stores/general';
	import { onMount } from 'svelte';

	let { data, children } = $props();

	let inIframe = $state(false);
	let showCollapsedSidebarOnly = $derived(data.showCollapsedSidebarOnly);
	onMount(() => {
		inIframe = window.self !== window.top;
	});
</script>

<div
	class={`main-panel absolute top-24 left-0 z-10 mr-4 ml-4 h-[calc(100%-6rem)] w-[calc(100%-2rem)] overflow-hidden transition-all print:!static print:!top-0 print:!left-0 print:!z-auto print:!m-0 print:!h-auto print:!w-full print:!overflow-visible print:!p-0  ${
		$appMenuOpen ? 'left-[90%]' : ''
	} ${!inIframe || !showCollapsedSidebarOnly ? 'lg:static lg:h-full' : ''}`}
>
	<div
		class="relative h-full grow overflow-hidden rounded-t-4xl bg-white print:!h-auto print:!overflow-visible print:!rounded-none print:!bg-transparent"
	>
		{#if !!$navigating || $loading}
			<div
				class="absolute top-0 left-0 z-[9999] flex h-full w-full items-center bg-white/75 print:!hidden"
			>
				<div class="m-auto flex flex-col items-center gap-5" transition:blur={{ amount: 10 }}>
					<Pulse color="#0ea5e9" />
					{#if $loadingMessage}
						<p>{$loadingMessage}</p>
					{/if}
				</div>
			</div>
		{/if}
		{@render children?.()}
	</div>
</div>
