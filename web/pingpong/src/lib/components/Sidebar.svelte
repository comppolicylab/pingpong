<script lang="ts">
	import { page } from '$app/stores';
	import {
		CloseOutline,
		UserSettingsOutline,
		QuestionCircleOutline,
		ArrowRightToBracketOutline,
		EyeSlashOutline,
		BarsOutline,
		CirclePlusSolid,
		DotsVerticalOutline,
		ArrowRightOutline,
		CogOutline,
		EyeOutline,
		UserCircleSolid,
		FileLinesOutline,
		MicrophoneOutline,
		UserOutline,
		BadgeCheckOutline,
		UsersOutline,
		InboxOutline
	} from 'flowbite-svelte-icons';

	import {
		Li,
		Dropdown,
		DropdownItem,
		DropdownDivider,
		Avatar,
		Sidebar,
		SidebarWrapper,
		SidebarItem,
		SidebarGroup,
		NavBrand,
		Tooltip,
		Button
	} from 'flowbite-svelte';
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';
	import dayjs from '$lib/time';
	import * as api from '$lib/api';
	import { anonymousShareToken } from '$lib/stores/anonymous';
	import type { LayoutData } from '../../routes/$types';
	import { appMenuOpen } from '$lib/stores/general';
	import { afterNavigate, goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { ltiHeaderState } from '$lib/stores/ltiHeader';

	export let data: LayoutData;

	// Get info about assistant provenance
	const getAssistantMetadata = (assistant: api.Assistant) => {
		const isCourseAssistant = assistant.endorsed;
		const isMyAssistant = assistant.creator_id === data.me.user!.id;
		return {
			creator: isCourseAssistant ? 'Moderation Team' : data.me.user!.name,
			isCourseAssistant,
			isMyAssistant
		};
	};
	$: hasLtiHeaderComponent = $ltiHeaderState.kind !== 'none';
	$: sharedPage = data.isSharedAssistantPage || data.isSharedThreadPage;
	$: forceShowSidebarButton = data.forceShowSidebarButton;
	$: forceCollapsedLayout = data.forceCollapsedLayout;
	$: openAllLinksInNewTab = data.openAllLinksInNewTab;
	$: logoIsClickable = data.logoIsClickable;
	$: showSidebarItems = data.showSidebarItems;
	$: isSharedAssistantPage = data.isSharedAssistantPage;
	$: isSharedThreadPage = data.isSharedThreadPage;
	$: shareToken = data.shareToken;
	$: pathName = $page.url.pathname;
	$: nonAuthed = (data.isPublicPage && !data?.me?.user) || data?.me?.status === 'anonymous';
	$: avatar = data?.me?.profile?.image_url;
	$: name = data?.me?.user?.name || data?.me?.user?.email;
	// Index classes by ID so we can look them up easier.
	$: classesById = ($page.data.classes || []).reduce(
		(acc: Record<number, api.Class>, cls: api.Class) => {
			acc[cls.id] = cls;
			return acc;
		},
		{}
	);
	$: threads = ($page.data.threads || []) as api.Thread[];
	$: currentClassId = parseInt($page.params.classId ?? '', 10);
	$: currentAssistantIdQuery = parseInt($page.url.searchParams.get('assistant') || '0', 10);
	$: currentAssistantId = $page.data.threadData?.thread?.assistant_id || currentAssistantIdQuery;
	$: assistants = [...(($page.data.assistants || []) as api.Assistant[])].sort((a, b) => {
		// First sort by endorsement.
		if (a.endorsed && !b.endorsed) return -1;
		if (!a.endorsed && b.endorsed) return 1;
		// Then sort by whether the assistant was created by the current user.
		if (a.creator_id === data.me.user!.id && b.creator_id !== data.me.user!.id) return -1;
		if (a.creator_id !== data.me.user!.id && b.creator_id === data.me.user!.id) return 1;
		// Finally, sort alphabetically by name.
		return a.name.localeCompare(b.name);
	});
	let assistantsToShow: api.Assistant[] = [];
	// Offer the top 4 assistants. If the current assistant is not in the top 4, add it to the top and remove the 4th one.
	$: if (assistants.length > 4) {
		assistantsToShow = assistants.slice(0, 4);
		if (currentAssistantId && !assistantsToShow.some((a) => a.id === currentAssistantId)) {
			const foundAssistant = assistants.find((a) => a.id === currentAssistantIdQuery);
			if (foundAssistant) {
				assistantsToShow.unshift(foundAssistant);
				assistantsToShow.pop();
			}
		}
	} else {
		assistantsToShow = assistants;
	}
	$: assistantMetadata = assistants.reduce(
		(acc: Record<number, ReturnType<typeof getAssistantMetadata>>, assistant) => {
			acc[assistant.id] = getAssistantMetadata(assistant);
			return acc;
		},
		{}
	);
	$: onNewChatPage = $page.url.pathname === `/group/${currentClassId}`;
	$: canViewSpecificClass = data.classes.some((cls) => cls.id === currentClassId);
	$: hasNoClasses = !nonAuthed && data.classes?.length === 0;

	// Toggle whether menu is open.
	const togglePanel = (state?: boolean) => {
		if (state !== undefined) {
			$appMenuOpen = state;
		} else {
			$appMenuOpen = !$appMenuOpen;
		}
	};

	type Placement = 'top-end' | 'right-start';
	let placement: Placement = 'top-end';
	let isLgOrWider = false;
	function updatePlacement() {
		if (window.innerWidth >= 1024) {
			// lg breakpoint
			placement = 'right-start';
			isLgOrWider = true;
		} else {
			placement = 'top-end';
			isLgOrWider = false;
		}
	}

	// Close the menu when navigating.
	afterNavigate(() => {
		// Don't close the sidebar in LTI context on lg or larger screens
		if (!(forceCollapsedLayout && forceShowSidebarButton && isLgOrWider)) {
			togglePanel(false);
		}
		dropdownOpen = false;
	});

	let dropdownOpen = false;
	const goToPage = async (
		destination: '/about' | '/privacy-policy' | '/admin' | '/logout' | '/profile'
	) => {
		dropdownOpen = false;
		await goto(resolve(destination));
	};

	let inIframe = false;
	onMount(() => {
		inIframe = window.self !== window.top;
		updatePlacement();
		window.addEventListener('resize', updatePlacement);
		return () => window.removeEventListener('resize', updatePlacement);
	});
</script>

<Sidebar
	asideClass={`absolute top-0 left-0 ${forceCollapsedLayout && forceShowSidebarButton && hasLtiHeaderComponent ? '-z-1 md:z-0' : 'z-0'} px-2 h-full ${
		forceCollapsedLayout && forceShowSidebarButton ? 'w-80' : 'w-[90%] md:w-80'
	} ${!inIframe || !forceCollapsedLayout ? 'lg:static lg:h-full lg:w-full' : ''}`}
	activeUrl={$page.url.pathname}
>
	<SidebarWrapper class="flex h-full flex-col bg-transparent">
		<SidebarGroup class="mb-6">
			<div class="flex items-center" data-sveltekit-preload-data="off">
				{#if !(inIframe && sharedPage) || forceShowSidebarButton}
					<button
						class="menu-button mt-1 mr-3 border-none bg-transparent {inIframe &&
						forceCollapsedLayout
							? ''
							: 'lg:hidden'}"
						onclick={() => togglePanel()}
					>
						{#if $appMenuOpen}
							<CloseOutline size="xl" class="menu-close text-white" />
						{:else}
							<BarsOutline size="xl" class="menu-open text-white" />
						{/if}
					</button>
				{/if}
				<NavBrand
					href={(inIframe && sharedPage) || !logoIsClickable ? undefined : '/'}
					class={forceCollapsedLayout && forceShowSidebarButton && hasLtiHeaderComponent
						? 'hidden md:block'
						: ''}
					target={openAllLinksInNewTab ? '_blank' : undefined}
				>
					<PingPongLogo size={10} extraClass="fill-amber-600" />
				</NavBrand>
			</div>
		</SidebarGroup>
		{#if showSidebarItems}
			<SidebarGroup
				class="mt-6 {forceCollapsedLayout && forceShowSidebarButton ? 'pt-6 md:pt-0' : ''}"
			>
				<SidebarItem
					target={openAllLinksInNewTab ? '_blank' : undefined}
					href={nonAuthed
						? isSharedAssistantPage
							? `/login?forward=${pathName}%3Fshare_token=${shareToken}`
							: isSharedThreadPage
								? `/group/${currentClassId}/shared/assistant/${currentAssistantId}?share_token=${$anonymousShareToken}`
								: '/login'
						: onNewChatPage || hasNoClasses
							? undefined
							: sharedPage
								? `/`
								: currentClassId
									? `/group/${currentClassId}${
											currentAssistantId ? `?assistant=${currentAssistantId}` : ''
										}`
									: '/'}
					label={nonAuthed
						? isSharedAssistantPage
							? 'Login to save this chat'
							: isSharedThreadPage
								? 'Start a new chat'
								: 'Login'
						: 'Start a new chat'}
					class={`flex flex-row-reverse justify-between rounded-full pr-4 text-white ${
						onNewChatPage || hasNoClasses
							? 'cursor-default bg-blue-dark-40 text-blue-dark-30 select-none hover:bg-blue-dark-40'
							: 'bg-orange hover:bg-orange-dark'
					} ${onNewChatPage || hasNoClasses ? 'disabled' : ''}`}
				>
					<svelte:fragment slot="icon">
						{#if nonAuthed && !isSharedThreadPage}
							<UserCircleSolid size="sm" />
						{:else}
							<CirclePlusSolid size="sm" />
						{/if}
					</svelte:fragment>
				</SidebarItem>
			</SidebarGroup>

			{#if nonAuthed}
				<SidebarGroup border class="overflow-y-auto border-t-3 border-blue-dark-40 pt-1">
					<SidebarItem
						target={openAllLinksInNewTab ? '_blank' : undefined}
						href="/about"
						label="Home"
						class="flex flex-wrap gap-2 rounded p-2 text-sm text-white hover:bg-blue-dark-40"
						activeClass="bg-blue-dark-40"
					/>
					<SidebarItem
						target={openAllLinksInNewTab ? '_blank' : undefined}
						href="/privacy-policy"
						label="Privacy Policy"
						class="flex flex-wrap gap-2 rounded p-2 text-sm text-white hover:bg-blue-dark-40"
						activeClass="bg-blue-dark-40"
					/>
				</SidebarGroup>
			{:else}
				<SidebarGroup
					class="{forceCollapsedLayout && forceShowSidebarButton
						? ''
						: 'mt-6'} flex flex-col overflow-y-auto pr-3"
					ulClass="flex-1"
				>
					{#if !sharedPage || canViewSpecificClass}
						<SidebarGroup ulClass="flex flex-wrap justify-between gap-2 items-center mt-4">
							<span class="flex-1 truncate text-white">Group Assistants</span>
							<Button
								href={`/group/${currentClassId}/assistant`}
								class="flex flex-wrap items-center justify-between gap-2 rounded p-2 text-white hover:bg-blue-dark-40"
								disabled={!currentClassId}
							>
								<span class="text-xs">View All</span><ArrowRightOutline
									size="md"
									class="ml-1 inline-block rounded-full bg-blue-dark-30 p-0.5 text-white"
								/>
							</Button>
						</SidebarGroup>
						<SidebarGroup
							border
							class="mt-1 border-t-3 border-blue-dark-40 pt-1"
							ulClass="space-y-0"
						>
							{#each assistantsToShow as assistant (assistant.id)}
								<SidebarItem
									class={'flex flex-wrap gap-2 truncate rounded-lg p-2 text-sm text-white ' +
										(currentAssistantIdQuery === assistant.id
											? 'bg-orange-dark hover:bg-orange'
											: 'hover:bg-blue-dark-30')}
									spanClass="flex-1 truncate"
									href={`/group/${currentClassId}?assistant=${assistant.id}`}
									label={assistant.name || 'Unknown Assistant'}
								>
									<svelte:fragment slot="icon">
										{#if assistantMetadata[assistant.id].isCourseAssistant}
											<BadgeCheckOutline size="sm" class="text-white" />
											<Tooltip>Group assistant</Tooltip>
										{:else if assistantMetadata[assistant.id].isMyAssistant}
											<UserOutline size="sm" class="text-white" />
											<Tooltip>Created by you</Tooltip>
										{:else}
											<UsersOutline size="sm" class="text-white" />
											<Tooltip>Shared by {assistantMetadata[assistant.id].creator}</Tooltip>
										{/if}
										{#if assistant.interaction_mode === 'voice'}
											<MicrophoneOutline size="sm" class="text-white" />
											<Tooltip>Voice mode assistant</Tooltip>
										{/if}
									</svelte:fragment>
								</SidebarItem>
							{/each}
							{#if !assistantsToShow.length}
								<div class="flex flex-wrap gap-2 rounded p-2 text-sm font-light text-white">
									{currentClassId ? 'No assistants available' : 'No group selected'}
								</div>
							{/if}
						</SidebarGroup>
					{/if}
					<SidebarGroup ulClass="flex flex-wrap justify-between gap-2 items-center mt-4">
						<span class="flex-1 truncate text-white">Recent Threads</span>
						<Button
							href={resolve(`/threads`)}
							class="flex flex-wrap items-center justify-between gap-2 rounded p-2 text-white hover:bg-blue-dark-40"
						>
							<span class="text-xs">View All</span><ArrowRightOutline
								size="md"
								class="ml-1 inline-block rounded-full bg-blue-dark-30 p-0.5 text-white"
							/>
						</Button>
					</SidebarGroup>
					<SidebarGroup
						border
						class="mt-1 flex flex-1 flex-col border-t-3 border-blue-dark-40 pt-1"
						ulClass="space-y-0 flex-1"
					>
						{#each threads as thread (thread.id)}
							<SidebarItem
								class="flex flex-wrap gap-2 rounded rounded-lg p-2 text-sm text-white hover:bg-blue-dark-30"
								spanClass="flex-1 truncate"
								href={thread.anonymous_session
									? resolve(`/group/${thread.class_id}/shared/thread/${thread.id}`)
									: resolve(`/group/${thread.class_id}/thread/${thread.id}`)}
								label={thread.name || 'New Conversation'}
								activeClass="bg-blue-dark-40"
							>
								<svelte:fragment slot="icon">
									<span class="eyebrow w-full"
										><div class="flex min-w-0 flex-row gap-1">
											<h4 class="max-w-1/2 shrink truncate">
												{classesById[thread.class_id]?.name ||
													(thread.anonymous_session ? 'Anonymous Session' : 'Unknown Group')}
											</h4>
											<h4 class="shrink-0">|</h4>
											<h4 class="min-w-0 shrink truncate">
												{Object.values(thread.assistant_names || { 1: 'Unknown Assistant' }).join(
													', '
												)}
											</h4>
										</div></span
									>
									{#if thread.private}
										<EyeSlashOutline size="sm" class="text-white" />
									{:else}
										<EyeOutline size="sm" class="text-white" />
									{/if}
									{#if thread.interaction_mode === 'voice'}
										<MicrophoneOutline size="sm" class="text-white" />
									{/if}
								</svelte:fragment>

								<svelte:fragment slot="subtext">
									<span class="w-full text-xs text-gray-400"
										>{dayjs.utc(thread.last_activity).fromNow()}</span
									>
								</svelte:fragment>
							</SidebarItem>
						{/each}
						{#if !threads.length}
							<div class="flex flex-1 flex-col items-center justify-center p-2 text-sm text-white">
								<InboxOutline class="mb-2 h-16 w-16 text-white" strokeWidth="1" />
								<span class="text-center text-lg font-medium">No recent threads</span>
								<span class="text-center font-light">Start a new chat to get started</span>
							</div>
						{/if}
					</SidebarGroup>
				</SidebarGroup>

				<SidebarGroup class="mt-auto border-t-3 border-blue-dark-40" border>
					<Li>
						<div
							class="user flex cursor-pointer items-center rounded-lg p-2 text-base font-normal text-white hover:bg-blue-dark-40 dark:text-white dark:hover:bg-gray-700"
						>
							<Avatar src={avatar} alt={name} />
							<span class="ml-3 truncate text-sm" title={name}>{name}</span>
							<DotsVerticalOutline size="lg" class="ml-auto" />
						</div>
					</Li>
				</SidebarGroup>
			{/if}
		{/if}
	</SidebarWrapper>
</Sidebar>

<Dropdown
	bind:open={dropdownOpen}
	class="w-40"
	classContainer="overflow-hidden"
	{placement}
	triggeredBy=".user"
>
	{#if $page.data.admin.showAdminPage}
		<DropdownItem onclick={() => goToPage('/admin')} class="flex items-center space-x-4">
			<CogOutline size="sm" />
			<span>Admin</span>
		</DropdownItem>
		<DropdownDivider />
	{/if}
	<DropdownItem onclick={() => goToPage('/profile')} class="flex items-center space-x-4">
		<UserSettingsOutline size="sm" />
		<span>Profile</span>
	</DropdownItem>
	<DropdownItem onclick={() => goToPage('/about')} class="flex items-center space-x-4">
		<QuestionCircleOutline size="sm" />
		<span>About</span>
	</DropdownItem>
	<DropdownItem onclick={() => goToPage('/privacy-policy')} class="flex items-center space-x-4">
		<FileLinesOutline size="sm" />
		<span>Privacy Policy</span>
	</DropdownItem>
	<DropdownDivider />
	<DropdownItem onclick={() => goToPage('/logout')} class="flex items-center space-x-4">
		<ArrowRightToBracketOutline size="sm" />
		<span>Logout</span>
	</DropdownItem>
</Dropdown>

<style lang="css">
	:global(.logo) {
		font-family: 'Rubik Doodle Shadow', system-ui;
		font-weight: 400;
		font-style: normal;
	}
</style>
