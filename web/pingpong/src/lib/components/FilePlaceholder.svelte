<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type {
    MimeTypeLookupFn,
    FileUploadInfo,
    FileUploadFailure,
    FileUploadPurpose
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
  export let info: FileUploadInfo;

  export let purpose: FileUploadPurpose = 'assistants';

  export let mimeType: MimeTypeLookupFn;

  export let preventDeletion = false;

  // Custom events
  const dispatch = createEventDispatcher();

  // Look up info about the file type.
  const nameForMimeType = (type: string) => {
    const mime = mimeType(type);
    return mime?.name || 'Unsupported!';
  };

  $: progress = info.progress;
  $: type = nameForMimeType(info.file.type);
  $: name = info.file.name;
  $: state = info.state;
  $: error = info.state === 'error' ? (info.response as FileUploadFailure).error : '';

  // Delete button clicked.
  const deleteFile = () => {
    dispatch('delete', info);
  };
</script>

<div
  class="cursor-default hover:shadow-sm relative rounded-lg items-center border-[1px] border-solid border-gray-300 bg-white flex px-2 -delete-button-container"
>
  <div>
    {#if state === 'pending'}
      {#if progress < 100}
        <ProgressCircle {progress} />
      {:else}
        <Jumper size="20" color="#0ea5e9" />
      {/if}
    {:else if state === 'deleting' && purpose === 'vision'}
      <ImageSolid class="w-6 h-6 text-red-500 animate-pulse" />
    {:else if state === 'deleting' && purpose !== 'vision'}
      <FileSolid class="w-6 h-6 text-red-500 animate-pulse" />
    {:else if state === 'success' && purpose === 'vision'}
      <ImageSolid class="w-6 h-6 text-green-500" />
    {:else if state === 'success' && purpose !== 'vision'}
      <FileSolid class="w-6 h-6 text-green-500" />
    {:else}
      <ExclamationCircleOutline class="w-6 h-6 text-red-500" />
      <Tooltip>Upload Error: {typeof error === 'string' ? error : error.detail}</Tooltip>
    {/if}
  </div>
  <div class="flex flex-col p-2">
    <div class="text-xs text-gray-500 font-bold">{name}</div>
    <div class="text-xs text-gray-500">{type}</div>
  </div>
  {#if state !== 'pending' && state !== 'deleting'}
    {#if !preventDeletion}
      <div class="absolute top-[-6px] right-[-6px] -delete-button">
        <Button pill color="dark" class="p-0" onclick={deleteFile}>
          <CloseOutline class="w-4 h-4" />
        </Button>
      </div>
    {:else if preventDeletion && purpose === 'vision'}
      <Tooltip arrow={false} class="font-light w-64"
        >This file is an image file and cannot be removed from the conversation. Delete the Thread
        to remove it.</Tooltip
      >
    {/if}
  {/if}
</div>

<style lang="css">
  .-delete-button {
    display: none;
  }
  .-delete-button-container:hover .-delete-button {
    display: block !important;
  }
</style>
