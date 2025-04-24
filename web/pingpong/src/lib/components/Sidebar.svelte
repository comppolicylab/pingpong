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
  import type { LayoutData } from '../../routes/$types';
  import { appMenuOpen } from '$lib/stores/general';
  import { afterNavigate, goto } from '$app/navigation';
  import { onMount } from 'svelte';

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

  $: nonAuthed = data.isPublicPage && !data?.me?.user;
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
  $: currentClassId = parseInt($page.params.classId, 10);
  $: currentAssistantIdQuery = parseInt($page.url.searchParams.get('assistant') || '0', 10);
  $: currentAssistantId = $page.data.threadData?.thread?.assistant_id || currentAssistantIdQuery;
  $: assistants = ($page.data.assistants || []) as api.Assistant[];
  $: assistants.sort((a, b) => {
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
  function updatePlacement() {
    if (window.innerWidth >= 1024) {
      // lg breakpoint
      placement = 'right-start';
    } else {
      placement = 'top-end';
    }
  }

  // Close the menu when navigating.
  afterNavigate(() => {
    togglePanel(false);
    dropdownOpen = false;
  });

  let dropdownOpen = false;
  const goToPage = async (destination: string) => {
    dropdownOpen = false;
    await goto(destination);
  };

  onMount(() => {
    updatePlacement();
    window.addEventListener('resize', updatePlacement);
    return () => window.removeEventListener('resize', updatePlacement);
  });
</script>

<Sidebar
  asideClass="absolute top-0 left-0 z-0 w-[90%] px-2 h-[100dvh] lg:static lg:h-full lg:w-full"
  activeUrl={$page.url.pathname}
>
  <SidebarWrapper class="bg-transparent h-full flex flex-col">
    <SidebarGroup class="mb-6">
      <div class="flex items-center" data-sveltekit-preload-data="off">
        <button
          class="menu-button bg-transparent border-none mr-3 mt-1 lg:hidden"
          on:click={() => togglePanel()}
        >
          {#if $appMenuOpen}
            <CloseOutline size="xl" class="text-white menu-close" />
          {:else}
            <BarsOutline size="xl" class="text-white menu-open" />
          {/if}
        </button>
        <NavBrand href="/" class="">
          <PingPongLogo size={10} extraClass="fill-amber-600" />
        </NavBrand>
      </div>
    </SidebarGroup>

    <SidebarGroup class="mt-6">
      <SidebarItem
        href={nonAuthed
          ? '/login'
          : onNewChatPage
            ? undefined
            : currentClassId
              ? `/group/${currentClassId}${
                  currentAssistantId ? `?assistant=${currentAssistantId}` : ''
                }`
              : '/'}
        label={nonAuthed ? 'Login' : 'Start a new chat'}
        class={`flex flex-row-reverse justify-between pr-4 text-white rounded-full ${
          onNewChatPage
            ? 'bg-blue-dark-40 hover:bg-blue-dark-40 cursor-default text-blue-dark-30 select-none'
            : 'bg-orange hover:bg-orange-dark'
        } ${onNewChatPage ? 'disabled' : ''}`}
      >
        <svelte:fragment slot="icon">
          {#if nonAuthed}
            <UserCircleSolid size="sm" />
          {:else}
            <CirclePlusSolid size="sm" />
          {/if}
        </svelte:fragment>
      </SidebarItem>
    </SidebarGroup>

    {#if nonAuthed}
      <SidebarGroup border class="overflow-y-auto border-blue-dark-40 border-t-3 pt-1">
        <SidebarItem
          href="/about"
          label="Home"
          class="text-sm text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap gap-2"
          activeClass="bg-blue-dark-40"
        />
        <SidebarItem
          href="/privacy-policy"
          label="Privacy Policy"
          class="text-sm text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap gap-2"
          activeClass="bg-blue-dark-40"
        />
      </SidebarGroup>
    {:else}
      <SidebarGroup class="flex flex-col overflow-y-auto mt-6 pr-3" ulClass="flex-1">
        <SidebarGroup ulClass="flex flex-wrap justify-between gap-2 items-center mt-4">
          <span class="flex-1 truncate text-white">Group Assistants</span>
          <Button
            href={`/group/${currentClassId}/assistant`}
            class="text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap justify-between gap-2 items-center"
            disabled={!currentClassId}
          >
            <span class="text-xs">View All</span><ArrowRightOutline
              size="md"
              class="text-white inline-block p-0.5 ml-1 rounded-full bg-blue-dark-30"
            />
          </Button>
        </SidebarGroup>
        <SidebarGroup border class={'border-blue-dark-40 border-t-3 pt-1 mt-1'} ulClass="space-y-0">
          {#each assistantsToShow as assistant}
            <SidebarItem
              class={'text-sm text-white p-2 rounded-lg flex flex-wrap gap-2 truncate ' +
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
            <div class="text-sm font-light text-white p-2 rounded flex flex-wrap gap-2">
              {currentClassId ? 'No assistants available' : 'No group selected'}
            </div>
          {/if}
        </SidebarGroup>

        <SidebarGroup ulClass="flex flex-wrap justify-between gap-2 items-center mt-4">
          <span class="flex-1 truncate text-white">Recent Threads</span>
          <Button
            href={`/threads`}
            class="text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap justify-between gap-2 items-center"
            disabled={threads.length === 0}
          >
            <span class="text-xs">View All</span><ArrowRightOutline
              size="md"
              class="text-white inline-block p-0.5 ml-1 rounded-full bg-blue-dark-30"
            />
          </Button>
        </SidebarGroup>
        <SidebarGroup
          border
          class="flex flex-col flex-1 border-blue-dark-40 border-t-3 pt-1 mt-1"
          ulClass="space-y-0 flex-1"
        >
          {#each threads as thread}
            <SidebarItem
              class="text-sm text-white hover:bg-blue-dark-30 p-2 rounded flex flex-wrap gap-2 rounded-lg"
              spanClass="flex-1 truncate"
              href={`/group/${thread.class_id}/thread/${thread.id}`}
              label={thread.name || 'New Conversation'}
              activeClass="bg-blue-dark-40"
            >
              <svelte:fragment slot="icon">
                <span class="eyebrow w-full"
                  ><div class="flex flex-row gap-1">
                    <h4 class="shrink-0">
                      {classesById[thread.class_id].name}
                    </h4>
                    <h4 class="shrink-0">|</h4>
                    <h4 class="shrink truncate">
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
                <span class="text-xs text-gray-400 w-full"
                  >{dayjs.utc(thread.last_activity).fromNow()}</span
                >
              </svelte:fragment>
            </SidebarItem>
          {/each}
          {#if !threads.length}
            <div class="flex-1 flex flex-col items-center justify-center text-sm text-white p-2">
              <InboxOutline class="text-white mb-2 w-16 h-16" strokeWidth="1" />
              <span class="text-center font-medium text-lg">No recent threads</span>
              <span class="text-center font-light">Start a new chat to get started</span>
            </div>
          {/if}
        </SidebarGroup>
      </SidebarGroup>

      <SidebarGroup class="mt-auto border-blue-dark-40 border-t-3" border>
        <Li>
          <div
            class="user cursor-pointer flex items-center p-2 text-base font-normal text-white rounded-lg dark:text-white hover:bg-blue-dark-40 dark:hover:bg-gray-700"
          >
            <Avatar src={avatar} alt={name} />
            <span class="ml-3 text-sm truncate" title={name}>{name}</span>
            <DotsVerticalOutline size="lg" class="ml-auto" />
          </div>
        </Li>
      </SidebarGroup>
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
    <DropdownItem on:click={() => goToPage('/admin')} class="flex space-x-4 items-center">
      <CogOutline size="sm" />
      <span>Admin</span>
    </DropdownItem>
    <DropdownDivider />
  {/if}
  <DropdownItem on:click={() => goToPage('/profile')} class="flex space-x-4 items-center">
    <UserSettingsOutline size="sm" />
    <span>Profile</span>
  </DropdownItem>
  <DropdownItem on:click={() => goToPage('/about')} class="flex space-x-4 items-center">
    <QuestionCircleOutline size="sm" />
    <span>About</span>
  </DropdownItem>
  <DropdownItem on:click={() => goToPage('/privacy-policy')} class="flex space-x-4 items-center">
    <FileLinesOutline size="sm" />
    <span>Privacy Policy</span>
  </DropdownItem>
  <DropdownDivider />
  <DropdownItem on:click={() => goToPage('/logout')} class="flex space-x-4 items-center">
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
