<script lang="ts">
  import { DropdownItem } from 'flowbite-svelte';
  export let value: string;
  export let selectedValue: string;
  export let update: (value: string) => void;
  export let name: string;
  export let subtitle: string;
  export let smallNameText: boolean = false;
</script>

<DropdownItem
  on:click={() => update(value)}
  defaultClass="flex flex-col gap-x-1 gap-y-1 font-medium py-2 px-4 text-sm scroll-mt-9 {value ==
  selectedValue
    ? 'text-blue-900 bg-blue-light-40 hover:bg-blue-light-40 hover:text-blue-900'
    : 'hover:bg-gray-100 dark:hover:bg-gray-600'}"
>
  <div class="flex flex-row gap-x-3 w-full flex-wrap items-center justify-between">
    <div class={smallNameText ? 'text-md' : 'text-lg'}>{name}</div>
    <div class="flex flex-row gap-x-1 gap-y-0.5 flex-wrap items-center">
      <slot />
    </div>
  </div>
  <span class="font-normal">{subtitle}</span>
</DropdownItem>
