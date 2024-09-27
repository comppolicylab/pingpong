<script lang="ts">
  import { FileSolid } from 'flowbite-svelte-icons';

  /**
   * Information about a file that is being uploaded.
   */
  export let file_id: string;
</script>

<div
  class="cursor-default hover:shadow relative rounded-lg items-center border-[1px] border-solid border-gray-300 flex px-2 -delete-button-container"
>
  <div>
    <FileSolid class="w-6 h-6 text-red-500" />
  </div>
  <div class="flex flex-col p-2">
    <div class="text-xs text-gray-500 font-bold">Unavailable File</div>
    <div class="text-xs text-gray-500">{file_id}</div>
  </div>
</div>
