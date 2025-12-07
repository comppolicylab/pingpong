<script lang="ts">
  import { DropdownItem } from 'flowbite-svelte';
  export let colorClasses: string = 'from-gray-800 to-gray-600';
  export let hoverable: boolean = false;
  export let hoverColorClasses: string = 'hover:from-gray-900 hover:to-gray-700';
  export let link: string = '';
</script>

{#if link}
  <!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
  <a href={link} data-sveltekit-reload rel="noopener noreferrer" target="_blank"
    ><DropdownItem
      class="bg-gradient-to-r {colorClasses} text-white {hoverable
        ? hoverColorClasses
        : ''} border-t rounded-b-lg"><slot /></DropdownItem
    ></a
  >
{:else}<DropdownItem
    class="bg-gradient-to-r {colorClasses} text-white {hoverable
      ? hoverColorClasses
      : ''} border-t rounded-b-lg"><slot /></DropdownItem
  >{/if}
