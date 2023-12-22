<script>
  import {page} from '$app/stores';
  import {
    CogOutline,
    FilePenOutline,
    UserSettingsOutline,
    QuestionCircleOutline, ArrowRightFromBracketSolid} from 'flowbite-svelte-icons';

  import {
    Li,
    Dropdown, DropdownItem, DropdownDivider,
    Avatar,
    Breadcrumb, BreadcrumbItem,
    Sidebar, SidebarBrand, SidebarWrapper, SidebarItem, SidebarGroup,
    SidebarDropdownWrapper, SidebarDropdownItem,
    Heading, NavBrand,
  } from 'flowbite-svelte';
  import Logo from "$lib/components/Logo.svelte";

  export let data;

  $: avatar = data?.me?.profile?.image_url;
  $: name = data?.me?.user?.name || data?.me?.user?.email;
  $: institutions = data?.institutions || [];
  $: classes = data?.classes || [];
  $: threads = (data?.threads || []).sort((a, b) => a.created > b.created ? -1 : 1);
  $: currentInstId = parseInt($page.params.institutionId, 10);
  $: currentClassId = parseInt($page.params.classId, 10);
  $: currentThreadId = parseInt($page.params.threadId, 10);
  $: currentInst = institutions.find(inst => inst.id === currentInstId);
  $: currentClass = classes.find(class_ => class_.id === currentClassId);
  $: canManageClass = !!currentClass && data?.me?.user?.super_admin;
</script>

<Sidebar asideClass="shrink-0 grow-0 w-80" activeUrl={$page.url.pathname}>
  <SidebarWrapper class="h-full flex flex-col">
    <SidebarGroup class="mb-4">
      <NavBrand href="/" class="mx-4">
        <Logo size="8" extraClass="fill-amber-600" />
        <Heading tag="h1" class="text-amber-500 px-4" customSize="text-xl">AI Tutor</Heading>
      </NavBrand>
    </SidebarGroup>

    {#if currentClassId}
    <SidebarGroup>
      <Breadcrumb>
        <BreadcrumbItem href={`/institution/${currentInstId}`}>{currentInst.name}</BreadcrumbItem>
      </Breadcrumb>
      <Breadcrumb class="mx-4 pr-4 w-full" olClass="w-full">
        <BreadcrumbItem spanClass="ms-1 text-sm font-medium text-gray-500 md:ms-2 dark:text-gray-400 flex items-center justify-between w-full" class="inline-flex items-center w-full">
          <span>{currentClass.name}</span>
          {#if canManageClass}
            <a href={`/institution/${currentInstId}/class/${currentClassId}/manage`}>
              <CogOutline size="sm" />
            </a>
          {/if}
        </BreadcrumbItem>
      </Breadcrumb>
    </SidebarGroup>

    <SidebarGroup border>
      <SidebarItem href={`/institution/${currentInstId}/class/${currentClassId}`} label="New Thread" class="text-amber-800">
        <svelte:fragment slot="icon">
          <FilePenOutline size="sm" />
        </svelte:fragment>
      </SidebarItem>
    </SidebarGroup>

    <SidebarGroup border class="overflow-y-auto">
      {#each threads as thread}
        <SidebarItem
          class="text-sm p-1"
          href={`/institution/${currentInstId}/class/${currentClassId}/thread/${thread.id}`}
          label={thread.name || "Undefined"} />
      {/each}
    </SidebarGroup>
    {:else}

    <SidebarGroup>
      {#each institutions as institution}
        {#if institution.id === currentInstId}
          <SidebarDropdownWrapper label={institution.name} isOpen={true} class="bg-gray-200">
            {#each classes as class_}
              <SidebarDropdownItem
                href={`/institution/${institution.id}/class/${class_.id}`}
                label={class_.name} />
            {/each}
          </SidebarDropdownWrapper>
        {:else}
          <SidebarItem label={institution.name} href={`/institution/${institution.id}`} />
        {/if}
      {/each}
    </SidebarGroup>
    {/if}

    <SidebarGroup class="mt-auto" border>
      <Li>
        <div class="user cursor-pointer flex items-center p-2 text-base font-normal text-gray-900 rounded-lg dark:text-white hover:bg-gray-100 dark:hover:bg-gray-700">
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
