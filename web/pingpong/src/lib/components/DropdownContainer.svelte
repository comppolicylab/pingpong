<script lang="ts">
  import { Dropdown } from 'flowbite-svelte';
  import { ChevronDownOutline } from 'flowbite-svelte-icons';
  export let dropdownOpen = false;
  export let placeholder = 'Select an option...';
</script>

<button
  id="model"
  name="model"
  class="flex flex-row grow justify-between items-center text-gray-900 bg-gray-50 border border-gray-300 rounded-lg focus:ring-primary-500 focus:border-primary-500 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-primary-500 dark:focus:border-primary-500 text-sm p-2.5"
  type="button"
>
  {placeholder}
  <ChevronDownOutline class="w-6 h-6 ms-2" />
</button>

<Dropdown
  class="py-0 rounded-lg"
  containerClass="dropdown-container w-1/2 border border-gray-300 flex flex-col z-10"
  placement="bottom-start"
  bind:open={dropdownOpen}
>
  <div class="relative rounded-lg">
    <div class="overflow-y-auto overscroll-contain rounded-t-lg flex-grow max-h-80 relative">
      <slot />
    </div>
    <slot name="footer" />
  </div>
</Dropdown>
