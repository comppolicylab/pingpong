<script lang="ts">
	import { appMenuOpen } from '$lib/stores/general';
	import { navigating } from '$app/stores';
	import { Pulse } from 'svelte-loading-spinners';
	import { blur } from 'svelte/transition';
	import { loading, loadingMessage } from '$lib/stores/general';
	import { onMount } from 'svelte';
	import { ltiHeaderComponent } from '$lib/stores/ltiHeader';

	export let data;
	export let isLtiHeaderLayout: boolean = false;

	let inIframe = false;
	$: forceCollapsedLayout = data.forceCollapsedLayout;
	$: isLtiHeaderLayout = isLtiHeaderLayout;
	$: isCollapsedSidebarOpen = $appMenuOpen && isLtiHeaderLayout;
	$: isMenuOpen = $appMenuOpen && !isCollapsedSidebarOpen;
	$: hasLtiHeaderComponent = !!$ltiHeaderComponent;
	onMount(() => {
		inIframe = window.self !== window.top;
	});
</script>

<div
	class={`main-panel absolute top-24 left-0 z-10 mr-4 ml-4 h-[calc(100%-6rem)] w-[calc(100%-2rem)] overflow-hidden transition-all print:!static print:!top-0 print:!left-0 print:!z-auto print:!m-0 print:!h-auto print:!w-full print:!overflow-visible print:!p-0 ${
		!inIframe || !forceCollapsedLayout ? 'lg:static lg:h-full' : ''
	}`}
	class:left-80={isCollapsedSidebarOpen}
	class:ml-0={isCollapsedSidebarOpen}
	class:md:w-[calc(100%-2rem-20rem)]={isCollapsedSidebarOpen}
	class:left-[90%]={isMenuOpen}
	class:md:left-80={isMenuOpen}
	class:pb-4={isLtiHeaderLayout}
>
	<div
		class="relative h-full grow overflow-hidden bg-white transition-all print:!h-auto print:!overflow-visible print:!rounded-none print:!bg-transparent"
		class:rounded-tl-4xl={isLtiHeaderLayout}
		class:rounded-t-4xl={!isLtiHeaderLayout || !hasLtiHeaderComponent}
		class:md:rounded-tl-none={$appMenuOpen && isLtiHeaderLayout && hasLtiHeaderComponent}
		class:rounded-b-4xl={isLtiHeaderLayout}
	>
		{#if !!$navigating || $loading}
			<div
				class="absolute top-0 left-0 z-[9998] flex h-full w-full items-center bg-white/75 print:!hidden"
			>
				<div class="m-auto flex flex-col items-center gap-5" transition:blur={{ amount: 10 }}>
					<Pulse color="#0ea5e9" />
					{#if $loadingMessage}
						<p>{$loadingMessage}</p>
					{/if}
				</div>
			</div>
		{/if}
		<slot />
	</div>
</div>
