<script lang="ts">
  import { Badge, DropdownItem } from 'flowbite-svelte';
  import { ImageOutline, StarSolid } from 'flowbite-svelte-icons';
  export let value: string;
  export let selectedModel: string;
  export let updateSelectedModel: (model: string) => void;
  export let showRecommended: boolean;
  export let showNew: boolean;
  export let showVision: boolean;
  export let name: string;
  export let description: string;
  export let smallNameText: boolean = false;
  let badgeStyles = 'flex flex-row items-center gap-x-1 py-0.5 px-2 border text-xs normal-case';
</script>

<DropdownItem
  on:click={() => updateSelectedModel(value)}
  defaultClass={value == selectedModel
    ? 'flex flex-col gap-x-1 font-medium py-2 px-4 text-sm text-blue-900 bg-blue-light-50 hover:bg-blue-light-50 hover:text-blue-900'
    : 'flex flex-col gap-x-1 font-medium py-2 px-4 text-sm hover:bg-gray-100 dark:hover:bg-gray-600'}
>
  <div class="flex flex-row gap-x-3 w-full flex-wrap items-center justify-between">
    <div class={smallNameText ? 'text-md' : 'text-lg'}>{name}</div>
    <div class="flex flex-row gap-x-1 gap-y-0.5 flex-wrap items-center">
      {#if showRecommended}
        <Badge
          class="flex flex-row items-center gap-x-1 py-0.5 px-2 border border-amber-400 bg-amber-50 text-amber-700 text-xs normal-case"
          ><StarSolid size="sm" />Recommended</Badge
        >
      {/if}
      {#if showNew}
        <Badge class="{badgeStyles} border-teal-400 bg-emerald-100 text-teal-900">New</Badge>
      {/if}
      {#if showVision}
        <Badge class="{badgeStyles} border-gray-400 bg-gray-100 text-gray-900"
          ><ImageOutline size="sm" />Vision capabilities</Badge
        >
      {/if}
    </div>
  </div>
  <span class="font-normal">{description}</span>
</DropdownItem>
