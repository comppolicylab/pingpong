<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { FileUploadInfo } from '$lib/api';
  import { CloseCircleSolid, FileSolid, ExclamationCircleOutline } from 'flowbite-svelte-icons';
  import { Tooltip, Button } from 'flowbite-svelte';
  import ProgressCircle from './ProgressCircle.svelte';
  import { Jumper } from 'svelte-loading-spinners';

  /**
   * Information about a file that is being uploaded.
   */
  export let info: FileUploadInfo;

  export let mimeType: (type: string) => string;

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
  $: error = info.state === 'error' ? info.response.error : '';

  // Delete button clicked.
  const deleteFile = () => {
    dispatch('delete', info);
  };
</script>

<div
  class="cursor-default hover:shadow relative rounded-lg items-center border-[1px] border-solid border-gray-300 flex px-2 -delete-button-container"
>
  <div>
    {#if state === 'pending'}
      {#if progress < 100}
        <ProgressCircle {progress} />
      {:else}
        <Jumper size="20" color="#0ea5e9" />
      {/if}
    {:else if state === 'deleting'}
      <FileSolid class="w-6 h-6 text-red-500 animate-pulse" />
    {:else if state === 'success'}
      <FileSolid class="w-6 h-6 text-green-500" />
    {:else}
      <ExclamationCircleOutline class="w-6 h-6 text-red-500" />
      <Tooltip>{error}</Tooltip>
    {/if}
  </div>
  <div class="flex flex-col p-2">
    <div class="text-xs text-gray-500 font-bold">{name}</div>
    <div class="text-xs text-gray-500">{type}</div>
  </div>
  {#if state !== 'pending' && state !== 'deleting'}
    <div class="absolute top-[-6px] right-[-6px] -delete-button">
      <Button pill color="dark" class="p-0">
        <CloseCircleSolid class="w-4 h-4" on:click={deleteFile} />
      </Button>
    </div>
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
