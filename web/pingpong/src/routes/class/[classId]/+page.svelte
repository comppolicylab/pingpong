<script lang="ts">
  import { writable } from 'svelte/store';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { enhance } from '$app/forms';
  import ChatInput from '$lib/components/ChatInput.svelte';
  import { Helper, GradientButton, Dropdown, DropdownItem } from 'flowbite-svelte';
  import { EyeSlashOutline, ChevronDownSolid } from 'flowbite-svelte-icons';
  import { sadToast } from '$lib/toast';
  import * as api from '$lib/api';
  import type { Assistant, Thread } from '$lib/api';
  import type { SubmitFunction } from '@sveltejs/kit';

  /**
   * Application data.
   */
  export let data;

  // Whether the app is currently loading.
  let loading = writable(false);
  // Currently selected assistant.
  let assistant = writable(data?.assistants[0] || {});

  // Whether billing is set up for the class (which controls everything).
  $: isConfigured = data?.hasAssistants && data?.hasBilling;
  $: parties = data.me.user?.id || '';
  // The assistant ID from the URL.
  $: linkedAssistant = parseInt($page.url.searchParams.get('assistant') || '0', 10);
  $: {
    if (linkedAssistant && data?.assistants) {
      const selectedAssistant = (data?.assistants || []).find(
        (asst) => asst.id === linkedAssistant
      );
      if (selectedAssistant) {
        $assistant = selectedAssistant;
      }
    }
  }
  $: fileTypes = data.uploadInfo.fileTypesForAssistants($assistant);

  // Handle file upload
  const handleUpload = (f: File, onProgress: (p: number) => void) => {
    return api.uploadUserFile(data.class.id, data.me.user!.id, f, { onProgress });
  };

  // Handle file removal
  const handleRemove = async (fileId: number) => {
    const result = await api.deleteUserFile(fetch, data.class.id, data.me.user!.id, fileId);
    if (api.isErrorResponse(result)) {
      sadToast(`Failed to delete file. Error: ${result.detail || 'unknown error'}`);
      throw new Error(result.detail || 'unknown error');
    }
  };

  // Handle form submission
  const handleSubmit: SubmitFunction = () => {
    $loading = true;

    return ({ result }) => {
      if (result.type === 'success') {
        const data = result.data as { thread: Thread };
        goto(`/class/${data.thread.class_id}/thread/${data.thread.id}`);
      } else {
        $loading = false;
        sadToast(`Chat failed! Please try again. Error: ${JSON.stringify(result)}`);
      }
    };
  };

  // Set the new assistant selection.
  const selectAi = (asst: Assistant) => {
    goto(`/class/${data.class.id}/?assistant=${asst.id}`);
  };
</script>

<div class="v-full h-full flex items-center">
  <div class="m-auto w-10/12">
    {#if isConfigured}
      <div class="text-center my-2 w-full">
        <GradientButton color="tealToLime"
          >{$assistant.name} <ChevronDownSolid class="w-3 h-3 ms-2" /></GradientButton
        >
        <Dropdown>
          {#each data.assistants as asst}
            <DropdownItem on:click={() => selectAi(asst)} on:touchstart={() => selectAi(asst)}>
              {#if !asst.published}
                <EyeSlashOutline size="sm" class="inline-block mr-2 text-gray-400" />
              {/if}
              {asst.name}
              <Helper class="text-xs">{data.assistantCreators[asst.creator_id].email}</Helper>
            </DropdownItem>
          {/each}
        </Dropdown>
      </div>
      <form action="?/newThread" method="POST" use:enhance={handleSubmit}>
        <ChatInput
          mimeType={data.uploadInfo.mimeType}
          maxSize={data.uploadInfo.private_file_max_size}
          accept={fileTypes}
          loading={$loading}
          upload={handleUpload}
          remove={handleRemove}
        />
        <input type="hidden" name="assistant_id" bind:value={$assistant.id} />
        <input type="hidden" name="parties" bind:value={parties} />
      </form>
    {:else}
      <div class="text-center">
        {#if !data.hasAssistants}
          <h1 class="text-2xl font-bold">No assistants configured.</h1>
        {:else if !data.hasBilling}
          <h1 class="text-2xl font-bold">No billing configured.</h1>
        {:else}
          <h1 class="text-2xl font-bold">Class is not configured.</h1>
        {/if}
      </div>
    {/if}
  </div>
</div>
