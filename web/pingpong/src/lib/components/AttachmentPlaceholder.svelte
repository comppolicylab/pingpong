<script lang="ts">
  import type { MimeTypeLookupFn, ServerFile } from '$lib/api';
  import { FileSolid } from 'flowbite-svelte-icons';

  /**
   * Information about a file that is being uploaded.
   */
  export let file: ServerFile;

  export let mimeType: MimeTypeLookupFn;

  $: type = mimeType(file.content_type)?.name || 'Unsupported';
  $: name = file.name;
</script>

<div
  class="cursor-default hover:shadow relative rounded-lg items-center border-[1px] border-solid border-gray-300 flex px-2 -delete-button-container"
>
  <div>
    <FileSolid class="w-6 h-6 text-green-500" />
  </div>
  <div class="flex flex-col p-2">
    <div class="text-xs text-gray-500 font-bold">{name}</div>
    <div class="text-xs text-gray-500">{type}</div>
  </div>
</div>
