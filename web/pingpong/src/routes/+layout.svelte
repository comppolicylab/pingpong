<script>
	import '../app.css';
	import Sidebar from '../lib/components/Sidebar.svelte';
	import Main from '$lib/components/Main.svelte';
	import { SvelteToast } from '@zerodevx/svelte-toast';
	import { onMount } from 'svelte';
	import { detectBrowser } from '$lib/stores/general';
	import { ltiHeaderComponent, ltiHeaderProps } from '$lib/stores/ltiHeader';

	export let data;

	onMount(() => {
		detectBrowser();
	});

	$: showSidebar =
		((data.me &&
			data.me.user &&
			!data.needsOnboarding &&
			(!data.needsAgreements || !data.doNotShowSidebar)) ||
			(data.isPublicPage && !data.doNotShowSidebar) ||
			data.isSharedAssistantPage ||
			data.isSharedThreadPage) &&
		!data.doNotShowSidebar;
	$: showStatusPage = data.me?.user;
	$: showBackground = data.isSharedAssistantPage || data.isSharedThreadPage;
	$: forceCollapsedLayout = data.forceCollapsedLayout;
	$: forceShowSidebarButton = data.forceShowSidebarButton;
	$: isLtiHeaderLayout = forceCollapsedLayout && forceShowSidebarButton;
</script>

<SvelteToast />
{#if showSidebar}
	<div class="flex h-full w-full md:h-[calc(100vh-3rem)] {isLtiHeaderLayout ? 'md:gap-4' : 'lg:gap-4'}">
		<div
			class="sidebar min-w-0 shrink-0 grow-0 {isLtiHeaderLayout 
				? 'basis-16 md:basis-[320px]'
				: 'basis-[320px]'}"
		>
			<Sidebar {data} />
		</div>
		<div class="main-content flex min-w-0 shrink grow flex-col">
			{#if isLtiHeaderLayout && $ltiHeaderComponent}
				<div class="shrink-0 -mt-8 mr-4">
					<svelte:component this={$ltiHeaderComponent} {...$ltiHeaderProps} />
				</div>
			{/if}
			<Main {isLtiHeaderLayout} {data}>
				<slot />
			</Main>
		</div>
	</div>
	{#if showStatusPage && data.hasNonComponentIncidents}
		<script src="https://pingpong-hks.statuspage.io/embed/script.js"></script>
	{/if}
{:else if showBackground}
	<Main {data}>
		<slot />
	</Main>
{:else}
	<slot />
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
