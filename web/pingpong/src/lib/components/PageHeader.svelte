<script lang="ts">
  import { Button, Dropdown, DropdownItem } from 'flowbite-svelte';
  import { ChevronDownSolid } from 'flowbite-svelte-icons';
  import * as api from '$lib/api';

  export let classes: api.Class[];
  export let current: api.Class | null = null;

  $: sortedClasses = classes.sort((a: api.Class, b: api.Class) => a.name.localeCompare(b.name));
</script>

<header class="bg-blue-light-50 p-8 pb-4 pt-10">
  <div class="eyebrow eyebrow-dark ml-4">Select class</div>
  <Button class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4">{current?.name || 'no class'} <ChevronDownSolid size="sm" class="bg-white rounded-full ml-4 h-8 w-8 inline-block text-orange"/></Button>
  <Dropdown class="w-64 overflow-y-auto py-1 h-36">
    {#each sortedClasses as cls}
      <DropdownItem
        class="flex items-center text-base font-semibold gap-4 py-4 text-sm tracking-wide font-medium uppercase hover:bg-blue-light-50"
        href={`/class/${cls.id}`}>{cls.name}</DropdownItem
      >
    {/each}
  </Dropdown>
</header>
