<script>
  import {
    UserSettingsOutline,
    QuestionCircleOutline, ArrowRightFromBracketSolid} from 'flowbite-svelte-icons';

  import {
    Li,
    Dropdown, DropdownItem, DropdownDivider,
    Avatar, Sidebar, SidebarBrand, SidebarWrapper, Heading, NavBrand, SidebarItem, SidebarGroup } from 'flowbite-svelte';
  import Logo from "./Logo.svelte";
  import {sha256} from 'js-sha256';

  export let data;

  $: avatar = data?.me?.profile?.image_url;
  $: name = data?.me?.user?.name || data?.me?.user?.email;
</script>

<Sidebar>
  <SidebarWrapper class="h-full flex flex-col">
    <SidebarGroup class="mb-4">
      <NavBrand href="/" class="mx-4">
        <Logo size="8" extraClass="fill-amber-600" />
        <Heading tag="h1" class="text-amber-500 px-4" customSize="text-xl">AI Tutor</Heading>
      </NavBrand>
    </SidebarGroup>
    <SidebarGroup>
      <SidebarItem label="Institution" />
    </SidebarGroup>
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
