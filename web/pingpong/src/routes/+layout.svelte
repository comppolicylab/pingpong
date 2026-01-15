<script lang="ts">
	import '../app.css';
	import Sidebar from '../lib/components/Sidebar.svelte';
	import Main from '$lib/components/Main.svelte';
	import { SvelteToast } from '@zerodevx/svelte-toast';
	import { onMount } from 'svelte';
	import { detectBrowser } from '$lib/stores/general';

	let { data, children } = $props();

	onMount(() => {
		detectBrowser();
	});

	let showSidebar = $derived(
		((data.me &&
			data.me.user &&
			!data.needsOnboarding &&
			(!data.needsAgreements || !data.doNotShowSidebar)) ||
			(data.isPublicPage && !data.doNotShowSidebar) ||
			data.isSharedAssistantPage ||
			data.isSharedThreadPage) &&
			!data.doNotShowSidebar
	);
	let showStatusPage = $derived(data.me?.user);
	let showBackground = $derived(data.isSharedAssistantPage || data.isSharedThreadPage);
</script>

<SvelteToast />
{#if showSidebar}
	<div class=" flex h-full w-full md:h-[calc(100vh-3rem)] lg:gap-4">
		<div class="sidebar min-w-0 shrink-0 grow-0 basis-[320px]">
			<Sidebar {data} />
		</div>
		<div class="main-content min-w-0 shrink grow">
			<Main {data}>
				{@render children?.()}
			</Main>
		</div>
	</div>
	{#if showStatusPage && data.hasNonComponentIncidents}
		<script src="https://pingpong-hks.statuspage.io/embed/script.js"></script>
	{/if}
{:else if showBackground}
	<Main {data}>
		{@render children?.()}
	</Main>
{:else}
	{@render children?.()}
{/if}

<style lang="css">
	:root {
		--toastBackground: #22c55e;
		--toastBorderRadius: 0.5rem;
		--toastBarBackground: #1d9e48;
	}

	@media print {
		.sidebar {
			display: none !important;
		}
		.main-content {
			flex-basis: 100% !important;
			max-width: 100% !important;
		}
	}
</style>
