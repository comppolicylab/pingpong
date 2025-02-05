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
    FileLinesOutline
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
    NavBrand
  } from 'flowbite-svelte';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import dayjs from '$lib/time';
  import * as api from '$lib/api';
  import type { LayoutData } from '../../routes/$types';
  import { appMenuOpen } from '$lib/stores/general';
  import { afterNavigate, goto } from '$app/navigation';

  export let data: LayoutData;

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
  $: currentAssistantId = $page.data.threadData?.thread?.assistant_id;
  $: onNewChatPage = $page.url.pathname === `/group/${currentClassId}`;

  // Toggle whether menu is open.
  const togglePanel = (state?: boolean) => {
    if (state !== undefined) {
      $appMenuOpen = state;
    } else {
      $appMenuOpen = !$appMenuOpen;
    }
  };

  // Close the menu when navigating.
  afterNavigate(() => {
    togglePanel(false);
  });

  const logout = async () => {
    await goto('/logout');
  };
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

    <SidebarGroup class="mt-6 mb-10">
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
        disabled={onNewChatPage}
        label={nonAuthed ? 'Login' : 'Start a new chat'}
        class={`flex flex-row-reverse justify-between pr-4 text-white rounded-full ${
          onNewChatPage
            ? 'bg-blue-dark-40 hover:bg-blue-dark-40 cursor-default text-blue-dark-30 select-none'
            : 'bg-orange hover:bg-orange-dark'
        }`}
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
      <SidebarGroup ulClass="flex flex-wrap justify-between gap-2 items-center">
        <span class="flex-1 truncate text-white">Recent Threads</span>
        <a
          href={`/threads`}
          class="text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap justify-between gap-2 items-center"
        >
          <span class="text-xs">View All</span><ArrowRightOutline
            size="md"
            class="text-white inline-block p-0.5 ml-1 rounded-full bg-blue-dark-30"
          />
        </a>
      </SidebarGroup>
      <SidebarGroup border class="overflow-y-auto border-blue-dark-40 border-t-3 pt-1">
        {#each threads as thread}
          <SidebarItem
            class="text-sm text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap gap-2"
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
                    {Object.values(thread.assistant_names || { 1: 'Unknown Assistant' }).join(', ')}
                  </h4>
                </div></span
              >
              {#if thread.private}
                <EyeSlashOutline size="sm" class="text-white" />
              {:else}
                <EyeOutline size="sm" class="text-white" />
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
          <div class="text-sm text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap gap-2">
            No conversations yet!
          </div>
        {/if}
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

<Dropdown class="w-40" placement="right" triggeredBy=".user">
  {#if $page.data.admin.showAdminPage}
    <DropdownItem href="/admin" class="flex space-x-4 items-center">
      <CogOutline size="sm" />
      <span>Admin</span>
    </DropdownItem>
    <DropdownDivider />
  {/if}
  <DropdownItem href="/profile" class="flex space-x-4 items-center">
    <UserSettingsOutline size="sm" />
    <span>Profile</span>
  </DropdownItem>
  <DropdownItem href="/about" class="flex space-x-4 items-center">
    <QuestionCircleOutline size="sm" />
    <span>About</span>
  </DropdownItem>
  <DropdownItem href="/privacy-policy" class="flex space-x-4 items-center">
    <FileLinesOutline size="sm" />
    <span>Privacy Policy</span>
  </DropdownItem>
  <DropdownDivider />
  <DropdownItem on:click={logout} class="flex space-x-4 items-center">
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
