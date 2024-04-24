<script lang="ts">
  import { Button, Dropdown, DropdownItem } from 'flowbite-svelte';
  import * as api from '$lib/api';

  export let classes: api.Class[];
  export let current: api.Class | null = null;

  $: sortedClasses = classes.sort((a: api.Class, b: api.Class) => a.name.localeCompare(b.name));
</script>

<header class="bg-blue-light-50 p-8 pb-6">
  <div>Select class</div>
  <Button>{current?.name || 'no class'}</Button>
  <Dropdown class="w-48 overflow-y-auto py-1 h-48">
    {#each sortedClasses as cls}
      <DropdownItem
        class="flex items-center text-base font-semibold gap-2"
        href={`/class/${cls.id}`}>{cls.name}</DropdownItem
      >
    {/each}
  </Dropdown>
</header>
