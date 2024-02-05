<script lang="ts">
  import { page } from '$app/stores';
  import {
    CogOutline,
    BookOutline,
    FilePenOutline,
    UserSettingsOutline,
    QuestionCircleOutline,
    ArrowRightFromBracketSolid,
    EyeSlashOutline
  } from 'flowbite-svelte-icons';

  import {
    Li,
    Dropdown,
    DropdownItem,
    DropdownDivider,
    Avatar,
    Breadcrumb,
    BreadcrumbItem,
    Sidebar,
    SidebarWrapper,
    SidebarItem,
    SidebarGroup,
    Heading,
    NavBrand
  } from 'flowbite-svelte';
  import Logo from '$lib/components/Logo.svelte';
  import dayjs from '$lib/time';
  import type { LayoutData } from './$types';

  export let data: LayoutData;

  $: avatar = data?.me?.profile?.image_url;
  $: name = data?.me?.user?.name || data?.me?.user?.email;
  $: classes = data?.classes || [];
  $: threads = (data?.threads || []).sort((a, b) => (a.created > b.created ? -1 : 1));
  $: currentClassId = parseInt($page.params.classId, 10);
  $: currentClass = classes.find((class_) => class_.id === currentClassId);
</script>

<Sidebar asideClass="shrink-0 grow-0 w-80" activeUrl={$page.url.pathname}>
  <SidebarWrapper class="h-full flex flex-col">
    <SidebarGroup class="mb-4">
      <NavBrand href="/" class="mx-4">
        <Logo size={10} extraClass="fill-amber-600" />
        <Heading tag="h1" class="text-amber-500 px-5 logo" customSize="text-3xl">PingPong</Heading>
      </NavBrand>
    </SidebarGroup>

    {#if currentClassId}
      <SidebarGroup>
        <Breadcrumb class="pr-2 w-full" olClass="w-full">
          <BreadcrumbItem
            spanClass="ms-1 text-sm font-medium text-gray-500 md:ms-2 dark:text-gray-400 flex items-center justify-between w-full"
            class="inline-flex items-center w-full"
          >
            <svelte:fragment slot="icon">
              <BookOutline class="text-gray-400" size="sm" />
            </svelte:fragment>
            <a href={`/class/${currentClassId}`}>{currentClass?.name}</a>
            <a href={`/class/${currentClassId}/manage`}>
              <CogOutline size="sm" />
            </a>
          </BreadcrumbItem>
        </Breadcrumb>
      </SidebarGroup>

      <SidebarGroup border>
        <SidebarItem href={`/class/${currentClassId}`} label="New Thread" class="text-amber-800">
          <svelte:fragment slot="icon">
            <FilePenOutline size="sm" />
          </svelte:fragment>
        </SidebarItem>
      </SidebarGroup>

      <SidebarGroup border class="overflow-y-auto">
        {#each threads as thread}
          <SidebarItem
            class="text-sm p-1 flex gap-2"
            spanClass="flex-1 truncate"
            href={`/class/${currentClassId}/thread/${thread.id}`}
            label={thread.name || 'Undefined'}
          >
            <svelte:fragment slot="icon">
              <EyeSlashOutline
                size="sm"
                class={`text-gray-400 ${thread.private ? 'visible' : 'invisible'}`}
              />
            </svelte:fragment>
            <svelte:fragment slot="subtext">
              <span class="text-xs text-gray-400 ml-auto"
                >{dayjs.utc(thread.updated).fromNow()}</span
              >
            </svelte:fragment>
          </SidebarItem>
        {/each}
      </SidebarGroup>
    {:else}
      <SidebarGroup class="overflow-y-auto overflow-x-hidden">
        <Heading tag="h2" class="text-sm font-medium text-gray-500 md:ms-2 dark:text-gray-400"
          >Classes</Heading
        >
        {#each classes as cls}
          <SidebarItem label={cls.name} href={`/class/${cls.id}`} />
        {/each}
      </SidebarGroup>
    {/if}

    <SidebarGroup class="mt-auto" border>
      <Li>
        <div
          class="user cursor-pointer flex items-center p-2 text-base font-normal text-gray-900 rounded-lg dark:text-white hover:bg-gray-100 dark:hover:bg-gray-700"
        >
          <Avatar src={avatar} alt={name} />
          <span class="ml-3">{name}</span>
        </div>
      </Li>
    </SidebarGroup>
  </SidebarWrapper>
</Sidebar>

<Dropdown class="w-40" placement="top" triggeredBy=".user">
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
    <ArrowRightFromBracketSolid size="sm" />
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
