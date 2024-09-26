<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type {
    MimeTypeLookupFn,
    FileUploadInfo,
    FileUploadFailure,
    FileUploadPurpose,
    ServerFile
  } from '$lib/api';
  import {
    CloseOutline,
    FileSolid,
    ExclamationCircleOutline,
    ImageSolid
  } from 'flowbite-svelte-icons';
  import { Tooltip, Button } from 'flowbite-svelte';
  import ProgressCircle from './ProgressCircle.svelte';
  import { Jumper } from 'svelte-loading-spinners';

  /**
   * Information about a file that is being uploaded.
   */
  export let file: ServerFile;

  export let mimeType: MimeTypeLookupFn;

  // Custom events
  const dispatch = createEventDispatcher();

  // Look up info about the file type.
  const nameForMimeType = (type: string) => {
    const mime = mimeType(type);
    return mime?.name || 'Unsupported!';
  };

  $: type = file.content_type || '';
  $: name = file.name || 'Deleted file';

  // Delete button clicked.
  const deleteFile = () => {
    dispatch('delete', file);
  };
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
  <!-- {#if state !== 'pending' && state !== 'deleting'}
      <div class="absolute top-[-6px] right-[-6px] -delete-button">
        <Button pill color="dark" class="p-0" on:click={deleteFile}>
          <CloseOutline class="w-4 h-4" />
        </Button>
      </div>
    {/if} -->
</div>

<!-- <style lang="css">
    .-delete-button {
      display: none;
    }
    .-delete-button-container:hover .-delete-button {
      display: block !important;
    }
  </style>
   -->
