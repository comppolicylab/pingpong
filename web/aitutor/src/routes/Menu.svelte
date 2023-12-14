<script>
  import {page} from '$app/stores';
  import {
    CogOutline,
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
  import Logo from "./Logo.svelte";

  export let data;

  console.log(data);

  $: avatar = data?.me?.profile?.image_url;
  $: name = data?.me?.user?.name || data?.me?.user?.email;
  $: institutions = data?.institutions || [];
  $: classes = data?.classes || [];
  $: threads = data?.threads || [];
  $: currentInstId = parseInt($page.params.institutionId, 10);
  $: currentClassId = parseInt($page.params.classId, 10);
  $: currentInst = institutions.find(inst => inst.id === currentInstId);
  $: currentClass = classes.find(class_ => class_.id === currentClassId);
  $: canManageClass = !!currentClass && data?.me?.user?.super_admin;
</script>

<Sidebar asideClass="shrink-0">
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
      <Breadcrumb>
        <BreadcrumbItem>{currentClass.name}</BreadcrumbItem>
      </Breadcrumb>
    </SidebarGroup>

    <SidebarGroup>
      <SidebarItem href={`/institution/${currentInstId}/class/${currentClassId}`} label="New Thread" />
      {#each threads as thread}
        <SidebarItem
          class={thread.id === $page.params.threadId ? 'bg-gray-200' : ''}
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
                class={class_.id === currentClassId ? 'bg-gray-200' : ''}
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

    {#if canManageClass}
      <SidebarGroup class="mt-auto" border>
        <SidebarItem href={`/institution/${currentInstId}/class/${currentClassId}/manage`} label="Manage">
          <svelte:fragment slot="icon">
            <CogOutline size="sm" />
          </svelte:fragment>
        </SidebarItem>
    </SidebarGroup>
    {/if}
    <SidebarGroup class={canManageClass ? "mt-4" : "mt-auto"} border>
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
