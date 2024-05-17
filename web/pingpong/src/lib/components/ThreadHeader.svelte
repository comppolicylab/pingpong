<script lang="ts">
  import { Button, Dropdown, DropdownItem } from 'flowbite-svelte';
  import { ChevronDownSolid, ArrowRightOutline, CogSolid } from 'flowbite-svelte-icons';
  import * as api from '$lib/api';
  import PageHeader, { mainTextClass } from './PageHeader.svelte';

  export let classes: api.Class[];
  export let isOnClassPage: boolean;
  export let current: api.Class | null = null;
  export let canManage: boolean = false;

  $: sortedClasses = classes.sort((a: api.Class, b: api.Class) => a.name.localeCompare(b.name));
</script>

<PageHeader>
  <div slot="left">
    <div class="eyebrow eyebrow-dark ml-4">Select class</div>
    <Button class={mainTextClass}
      >{current?.name || 'no class'}
      <ChevronDownSolid
        size="sm"
        class="bg-white rounded-full ml-4 h-8 w-8 inline-block text-orange"
      /></Button
    >
    <Dropdown class="w-64 overflow-y-auto py-1 h-36">
      {#each sortedClasses as cls}
        <DropdownItem
          class="flex items-center text-base font-semibold gap-4 py-4 text-sm tracking-wide font-medium uppercase hover:bg-blue-light-50"
          href={`/class/${cls.id}`}>{cls.name}</DropdownItem
        >
      {/each}
    </Dropdown>
  </div>
  <div slot="right">
    {#if current}
      {#if !isOnClassPage}
        <a
          href={`/class/${current.id}/assistant`}
          class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all">View class page <ArrowRightOutline size="md" class="text-orange inline-block ml-1" /></a
        >
      {:else if canManage}
        <a href={`/class/${current.id}/manage`} class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
          >Manage Class <CogSolid size="sm" class="text-orange inline-block ml-1 relative -top-[1px]" /></a
        >
      {/if}
    {/if}
  </div>
</PageHeader>
