<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import * as api from '$lib/api';
	import dayjs from '$lib/time';
	import { Select, Button } from 'flowbite-svelte';
	import AssistantVersionBadge from '$lib/components/AssistantVersionBadge.svelte';
	import { page } from '$app/stores';
	import { resolve } from '$app/paths';
	import { getValue, updateSearch } from '$lib/urlstate';
	import { loading } from '$lib/stores/general';
	import { afterUpdate } from 'svelte';
	import { ltiHeaderState } from '$lib/stores/ltiHeader';

	export let data;

	const classOptions = [
		{ value: '0', name: 'All' },
		...data.classes
			.map((cls) => ({ value: `${cls.id}`, name: cls.name }))
			.sort((a, b) => a.name.localeCompare(b.name))
	];
	$: currentClass = $page.url.searchParams.get('class_id') || '0';
	let threads = data.threadArchive.threads || [];
	let hasMore = !data.threadArchive.lastPage;
	let error = data.threadArchive.error;

	let lastData = data;
	afterUpdate(() => {
		if (data !== lastData) {
			threads = data.threadArchive.threads || [];
			hasMore = !data.threadArchive.lastPage;
			error = data.threadArchive.error;
			lastData = data;
		}
	});

	$: isLtiHeaderLayout = data.forceCollapsedLayout && data.forceShowSidebarButton;

	// Update props reactively when data changes
	$: if (isLtiHeaderLayout) {
		ltiHeaderState.set({
			kind: 'nongroup',
			props: {
				title: 'Threads Archive'
			}
		});
	}

	const classNamesLookup = data.classes.reduce(
		(acc, cls) => {
			acc[cls.id] = cls;
			return acc;
		},
		{} as Record<number, api.Class>
	);

	const fetchNextPage = async () => {
		if (!hasMore) {
			return;
		}

		if (error) {
			return;
		}

		$loading = true;

		const lastTs = threads.length ? threads[threads.length - 1].last_activity : undefined;
		const currentClassId = parseInt(currentClass, 10) || undefined;
		const more = await api.getAllThreads(fetch, { before: lastTs, class_id: currentClassId });
		$loading = false;
		if (more.error) {
			error = more.error;
		} else {
			threads = [...threads, ...more.threads];
			hasMore = !more.lastPage;
			error = null;
		}
	};
</script>

<div class="flex h-full w-full flex-col">
	{#if !isLtiHeaderLayout}
		<PageHeader>
			<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold" slot="left">
				Threads Archive
			</h2>
		</PageHeader>
	{/if}

	<!-- TODO: search is not yet fully supported. -->

	<div class="grid min-h-0 shrink grow gap-12 p-12 sm:grid-cols-[2fr_1fr]">
		<div class="sm:col-start-2 sm:col-end-3">
			<label for="class" class="block pt-8 pb-2 text-xs tracking-wide uppercase"
				>Filter by <b>Group</b></label
			>
			<Select
				items={classOptions}
				onchange={(e) => updateSearch('class_id', getValue(e.target))}
				value={currentClass}
				name="class"
			/>
		</div>

		<div class="h-full overflow-y-auto sm:col-start-1 sm:col-end-2 sm:row-start-1">
			<h3 class="border-b border-gray-200 pb-1 text-2xl font-normal">Threads</h3>
			<div class="flex flex-col flex-wrap">
				{#each threads as thread (thread.id)}
					{@const allUsers = thread.user_names || []}
					{@const allUsersLen = allUsers.length}
					{@const isCurrentUserParticipant =
						thread.is_current_user_participant || allUsers.includes('Me')}
					{@const isAnonymousSession = thread.anonymous_session || false}
					{@const otherUsers = thread.user_names?.filter((user_name) => user_name != 'Me') || []}
					{@const otherUsersLen = otherUsers.length}
					<a
						href={resolve(
							thread.anonymous_session && isCurrentUserParticipant
								? `/group/${thread.class_id}/shared/thread/${thread.id}`
								: `/group/${thread.class_id}/thread/${thread.id}`
						)}
						class="border-b border-gray-200 pt-4 pb-4 transition-all duration-300 hover:bg-gray-100 hover:pl-4"
					>
						<div>
							<div class="flex flex-row flex-wrap items-center gap-2">
								<h4 class="eyebrow eyebrow-dark shrink-0">
									{classNamesLookup[thread.class_id]?.name ||
										(thread.anonymous_session ? 'Anonymous Session' : 'Unknown Group')}
								</h4>
								<h4 class="eyebrow eyebrow-dark shrink-0">|</h4>
								<h4 class="eyebrow eyebrow-dark shrink truncate">
									{Object.values(thread.assistant_names || { 1: 'Unknown Assistant' }).join(', ')}
								</h4>
								<AssistantVersionBadge version={thread.version} extraClasses="shrink-0" />
							</div>
							<div class="pt-2 pb-2 text-lg font-light">
								{thread.name || 'New Conversation'}
							</div>
							<div class="pb-1 text-xs tracking-wide text-gray-400 uppercase">
								{dayjs.utc(thread.last_activity).fromNow()}
							</div>
							<div class="text-xs tracking-wide text-gray-400 uppercase">
								{allUsersLen > 0
									? thread.private && !thread.display_user_info
										? allUsersLen != otherUsersLen
											? `me${
													otherUsersLen > 0
														? otherUsersLen === 1
															? ' & Anonymous User'
															: ' & ' + otherUsersLen + ' Anonymous Users'
														: ''
												}`
											: 'Anonymous User'
										: allUsersLen != otherUsersLen
											? `me${
													otherUsersLen > 0
														? otherUsers
																.map((user_name) => user_name || 'Anonymous User')
																.join(', ')
														: ''
												}`
											: allUsers.map((user_name) => user_name || 'Anonymous User').join(', ')
									: isCurrentUserParticipant
										? 'Me'
										: isAnonymousSession
											? 'Anonymous Session User'
											: 'Anonymous User'}
							</div>
						</div>
					</a>
				{/each}

				{#if threads.length === 0}
					<div class="py-8 text-center text-sm tracking-wide text-gray-400 uppercase">
						No threads found
					</div>
				{/if}

				{#if error}
					<div class="py-8 text-center text-sm tracking-wide text-red-400 uppercase">
						Error: {error}
					</div>
				{/if}

				{#if hasMore}
					<div class="py-8 text-center tracking-wide uppercase">
						<Button
							class="tracking-wide text-blue-dark-40 uppercase hover:bg-gray-100"
							onclick={fetchNextPage}>Load more ...</Button
						>
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
