<script lang="ts">
  import { Button, Dropdown, DropdownItem, Search, Span } from 'flowbite-svelte';
  import { ChevronDownOutline, ArrowRightOutline, CogSolid } from 'flowbite-svelte-icons';
  import * as api from '$lib/api';
  import PageHeader, { mainTextClass } from './PageHeader.svelte';
  import { goto } from '$app/navigation';

  export let classes: api.Class[];
  export let isOnClassPage: boolean;
  export let current: api.Class | null = null;
  export let canManage: boolean = false;
  export let isSharedPage: boolean = false;

  $: sortedClasses = classes.sort((a: api.Class, b: api.Class) => a.name.localeCompare(b.name));
  let searchTerm = '';
  $: filteredClasses = sortedClasses.filter(
    (class_) => class_.name.toLowerCase().indexOf(searchTerm?.toLowerCase()) !== -1
  );

  let classDropdownOpen = false;
  const goToClass = async (clsId: number) => {
    classDropdownOpen = false;
    await goto(`/group/${clsId}`);
  };
</script>

{#if isSharedPage}
  <PageHeader>
    <div slot="left">
      <div class="eyebrow eyebrow-dark ml-4 mb-2">Shared Access</div>
      <Span class={mainTextClass}>{current?.name || 'no class'}</Span>
    </div>
    <div slot="right" class="flex flex-col items-end gap-2">
      {#if current}
        <div class="eyebrow eyebrow-dark ml-4 mr-4">Requires Login</div>

        <a
          href={`/group/${current.id}/assistant`}
          class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
          >View Group Page <ArrowRightOutline size="md" class="text-orange inline-block ml-1" /></a
        >
      {/if}
    </div>
  </PageHeader>
{:else}
  <PageHeader>
    <div slot="left">
      <div class="eyebrow eyebrow-dark ml-4">Select group</div>
      <Button class={mainTextClass}
        >{current?.name || 'no class'}
        <ChevronDownOutline
          size="sm"
          class="bg-white rounded-full ml-4 h-8 w-8 inline-block text-orange"
        /></Button
      >
      <Dropdown
        class="w-64 overflow-y-auto py-1 min-h-0 max-h-[400px]"
        bind:open={classDropdownOpen}
      >
        <div slot="header" class="w-64 p-3">
          <Search size="md" bind:value={searchTerm} />
        </div>
        {#each filteredClasses as cls}
          <DropdownItem
            class="flex items-center text-base font-semibold gap-4 py-4 text-sm tracking-wide font-medium uppercase hover:bg-blue-light-50"
            on:click={() => goToClass(cls.id)}>{cls.name}</DropdownItem
          >
        {/each}
      </Dropdown>
    </div>
    <div slot="right">
      {#if current}
        {#if !isOnClassPage}
          <a
            href={`/group/${current.id}/assistant`}
            class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
            >View Group Page <ArrowRightOutline
              size="md"
              class="text-orange inline-block ml-1"
            /></a
          >
        {:else if canManage}
          <a
            href={`/group/${current.id}/manage`}
            class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
            >Manage Group <CogSolid
              size="sm"
              class="text-orange inline-block ml-1 relative -top-[1px]"
            /></a
          >
        {/if}
      {/if}
    </div>
  </PageHeader>
{/if}
