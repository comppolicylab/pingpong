<script lang="ts">
  import { Dropdown } from 'flowbite-svelte';
  import { ChevronDownOutline } from 'flowbite-svelte-icons';
  import { afterUpdate } from 'svelte';

  // Whether to show the footer.
  export let footer = false;
  // Whether the dropdown is open.
  export let dropdownOpen = false;
  // The placeholder text shown in the dropdown button.
  export let placeholder = 'Select an option...';
  // The selected option.
  export let selectedOption: string;
  // The option nodes.
  export let optionNodes: Record<string, HTMLElement> = {};
  // The class of the header for each node, if any.
  export let optionHeaders: Record<string, string> = {};
  // The width of the dropdown as measured by the button width. Defaults to 3/5.
  export let width = 'w-3/5';
  // Whether the dropdown is disabled.
  export let disabled = false;

  let dropdownContainer: HTMLElement;

  afterUpdate(async () => {
    const currentNode = optionNodes[selectedOption];
    const headerClass = optionHeaders[selectedOption];
    if (currentNode && dropdownContainer) {
      const dropdownRect = dropdownContainer.getBoundingClientRect();
      const nodeRect = currentNode.getBoundingClientRect();

      let totalStickyHeight = 0;
      if (headerClass) {
        // Calculate total height of sticky headers
        const stickyHeaders = dropdownContainer.querySelectorAll(`.${headerClass}`);
        stickyHeaders.forEach((header) => {
          totalStickyHeight += (header as HTMLElement).offsetHeight;
        });
      }
      // Calculate the scroll position
      const scrollPosition =
        nodeRect.top - dropdownRect.top + dropdownContainer.scrollTop - totalStickyHeight;

      // Instant scroll to the calculated position
      dropdownContainer.scrollTo({
        top: Math.max(0, scrollPosition),
        behavior: 'instant'
      });
    }
  });
</script>

<div class="grow min-w-0 relative w-full">
  <button
    id="model"
    name="model"
    class="flex w-full items-center text-gray-900 bg-gray-50 border border-gray-300 rounded-lg focus:ring-3 focus:ring-primary-500 focus:border-primary-500 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-primary-500 dark:focus:border-primary-500 text-sm p-2.5 h-10 overflow-hidden"
    type="button"
    {disabled}
  >
    <span class="truncate grow text-left mr-2">{placeholder}</span>
    <ChevronDownOutline class="w-6 h-6 shrink-0" />
  </button>

  <Dropdown
    class="py-0 rounded-lg"
    containerClass="{width} border border-gray-300 flex flex-col z-10"
    placement="bottom-start"
    bind:open={dropdownOpen}
  >
    <div class="relative rounded-lg">
      <div
        class="overflow-y-auto overscroll-contain {footer
          ? 'rounded-t-lg'
          : 'rounded-lg'} grow max-h-80 relative"
        bind:this={dropdownContainer}
      >
        <slot />
      </div>
      <slot name="footer" />
    </div>
  </Dropdown>
</div>
