<script lang="ts">
	import '../app.css';
	import { ModeWatcher } from 'mode-watcher';
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import * as Breadcrumb from '$lib/components/ui/breadcrumb/index.js';
	import AppSidebar from '$lib/components/app-sidebar.svelte';
	import Separator from '$lib/components/ui/separator/separator.svelte';
	import { page } from '$app/state';
	import { Toaster } from '$lib/components/ui/sonner/index.js';
	import { courseById } from '$lib/stores/courses';
	import { fade } from 'svelte/transition';

	let { children } = $props();
	let courseStore = $state(courseById((page.params.courseId as string) || ''));
	$effect(() => {
		const id = (page.params.courseId as string) || '';
		courseStore = courseById(id);
	});

	let pageTitle = $derived(
		((page.url.pathname.startsWith('/preassessment/') ||
			page.url.pathname.startsWith('/courses/')) &&
			$courseStore?.name) ||
			page.data?.title ||
			'PingPong College Study'
	);
	let showSidebar = $derived(page.data?.showSidebar !== false);
</script>

<ModeWatcher />
<Toaster position="top-center" />
<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>
{#if showSidebar}
	<Sidebar.Provider class="h-dvh">
		<AppSidebar />
		<Sidebar.Inset>
			<header class="flex h-16 shrink-0 items-center gap-2 border-b">
				<div class="flex items-center gap-2 px-4">
					<Sidebar.Trigger class="-ml-1" />
					<Separator orientation="vertical" class="mr-2 data-[orientation=vertical]:h-4" />
					<Breadcrumb.Root>
						<Breadcrumb.List>
							<Breadcrumb.Item>
								<Breadcrumb.Page class="line-clamp-1 text-xl font-medium">
									{pageTitle}
								</Breadcrumb.Page>
							</Breadcrumb.Item>
						</Breadcrumb.List>
					</Breadcrumb.Root>
				</div>
			</header>
			<div class="flex flex-col overflow-auto p-4">
				{#key page.url.pathname}
					<div in:fade={{ duration: 150 }}>
						{@render children?.()}
					</div>
				{/key}
			</div>
		</Sidebar.Inset>
	</Sidebar.Provider>
	<script
		data-jsd-embedded
		data-key="66f55cfb-f3b4-44aa-a910-3f49aaedce06"
		data-base-url="https://jsd-widget.atlassian.com"
		src="https://jsd-widget.atlassian.com/assets/embed.js"
	></script>
	<script src="https://pingpong-hks.statuspage.io/embed/script.js"></script>
{:else}
	{@render children?.()}
{/if}
