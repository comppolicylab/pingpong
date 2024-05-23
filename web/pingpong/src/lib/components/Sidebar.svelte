<script lang="ts">
  import { page } from '$app/stores';
  import {
    CloseOutline,
    UserSettingsOutline,
    QuestionCircleOutline,
    ArrowRightToBracketSolid,
    EyeSlashOutline,
    BarsSolid,
    CirclePlusSolid,
    DotsVerticalOutline,
    ArrowRightOutline,
    CogOutline
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
  import { afterNavigate } from '$app/navigation';

  export let data: LayoutData;

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
            <BarsSolid size="xl" class="text-white menu-open" />
          {/if}
        </button>
        <NavBrand href="/" class="">
          <PingPongLogo size={10} extraClass="fill-amber-600" />
        </NavBrand>
      </div>
    </SidebarGroup>

    <SidebarGroup class="mt-6 mb-20">
      <SidebarItem
        href={`/class/${currentClassId}`}
        label="Start a new chat"
        class="flex flex-row-reverse justify-between pr-4 bg-orange text-white rounded-full hover:bg-orange-dark"
      >
        <svelte:fragment slot="icon">
          <CirclePlusSolid size="sm" />
        </svelte:fragment>
      </SidebarItem>
    </SidebarGroup>

    <SidebarGroup border class="overflow-y-auto border-blue-dark-40 border-t-3 pt-1">
      <a
        href={`/threads`}
        class="text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap justify-between gap-2 items-center"
      >
        <span class="flex-1 truncate">Recent Threads</span><span class="text-xs"
          >View All <ArrowRightOutline
            size="md"
            class="text-white inline-block p-0.5 ml-1 rounded-full bg-blue-dark-30"
          /></span
        >
      </a>
      {#each threads as thread}
        <SidebarItem
          class="text-sm text-white hover:bg-blue-dark-40 p-2 rounded flex flex-wrap gap-2"
          spanClass="flex-1 truncate"
          href={`/class/${thread.class_id}/thread/${thread.id}`}
          label={thread.name || 'Undefined'}
          activeClass="bg-blue-dark-40"
        >
          <svelte:fragment slot="icon">
            <span class="eyebrow w-full">{classesById[thread.class_id].name}</span>
            <EyeSlashOutline
              size="sm"
              class={`text-white ${thread.private ? 'visible' : 'invisible'}`}
            />
          </svelte:fragment>

          <svelte:fragment slot="subtext">
            <span class="text-xs text-gray-400 w-full">{dayjs.utc(thread.updated).fromNow()}</span>
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
          <span class="ml-3 text-sm">{name}</span>
          <DotsVerticalOutline size="lg" class="ml-auto" />
        </div>
      </Li>
    </SidebarGroup>
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
  <DropdownDivider />
  <DropdownItem href="/logout" class="flex space-x-4 items-center">
    <ArrowRightToBracketSolid size="sm" />
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
