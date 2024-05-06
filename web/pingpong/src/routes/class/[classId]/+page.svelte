<script lang="ts">
  import { blur } from 'svelte/transition';
  import { writable } from 'svelte/store';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { Pulse } from 'svelte-loading-spinners';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import { Button, Helper, Dropdown, DropdownItem } from 'flowbite-svelte';
  import { EyeSlashOutline, ChevronDownSolid } from 'flowbite-svelte-icons';
  import { sadToast } from '$lib/toast';
  import * as api from '$lib/api';
  import { errorMessage } from '$lib/errors';
  import type { Assistant } from '$lib/api';
  import { onMount } from 'svelte';

  /**
   * Application data.
   */
  export let data;

  onMount(() => {
    // Make sure that an assistant is linked in the URL
    if (!$page.url.searchParams.has('assistant')) {
      if (data.assistants.length > 0) {
        // replace current URL with one that has the assistant ID
        goto(`/class/${data.class.id}/?assistant=${data.assistants[0].id}`, { replaceState: true });
      }
    }
  });

  // Whether the app is currently loading.
  let loading = writable(false);
  // Currently selected assistant.
  $: assistants = data?.assistants || [];
  let assistant = writable(data?.assistants[0] || {});
  // Whether billing is set up for the class (which controls everything).
  $: isConfigured = data?.hasAssistants && data?.hasBilling;
  $: parties = data.me.user?.id ? `${data.me.user.id}` : '';
  // The assistant ID from the URL.
  $: linkedAssistant = parseInt($page.url.searchParams.get('assistant') || '0', 10);
  $: {
    if (linkedAssistant && assistants) {
      const selectedAssistant = (assistants || []).find((asst) => asst.id === linkedAssistant);
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
  const handleSubmit = async (e: CustomEvent<ChatInputMessage>) => {
    $loading = true;
    const form = e.detail;
    if (!form.message) {
      $loading = false;
      sadToast('Please enter a message.');
      return;
    }

    const partyIds = parties ? parties.split(',').map((id) => parseInt(id, 10)) : [];
    try {
      const newThread = api.explodeResponse(
        await api.createThread(fetch, data.class.id, {
          assistant_id: $assistant.id,
          parties: partyIds,
          message: form.message,
          file_ids: form.file_ids
        })
      );
      data.threads = [newThread, ...data.threads];
      goto(`/class/${$page.params.classId}/thread/${newThread.id}`);
    } catch (e) {
      sadToast(`Failed to create thread. Error: ${errorMessage(e)}`);
      $loading = false;
    }
  };

  // Set the new assistant selection.
  const selectAi = (asst: Assistant) => {
    goto(`/class/${data.class.id}/?assistant=${asst.id}`);
  };
</script>

<div class="flex items-center relative h-[calc(100%-5rem)] sm:h-[calc(100%-7rem)]">
  {#if $loading}
    <div class="absolute top-0 left-0 flex h-full w-full items-center">
      <div class="m-auto" transition:blur={{ amount: 10 }}>
        <Pulse color="#0ea5e9" />
      </div>
    </div>
  {/if}
  <div
    class="m-auto w-11/12 transition-opacity ease-in flex flex-col h-full py-3"
    class:opacity-0={$loading}
  >
    {#if isConfigured}
      <div class="my-2 w-full">
        <Button
          pill
          class="bg-blue-light-50 text-xs uppercase tracking-wide font-medium text-black border-solid border border-blue-dark-40"
          >{$assistant.name} <ChevronDownSolid class="w-3 h-3 ms-2" /></Button
        >
        <Dropdown class="max-h-60 overflow-y-auto w-60">
          {#each assistants as asst}
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
      <div class="mt-auto mb-8">
        <ChatInput
          mimeType={data.uploadInfo.mimeType}
          maxSize={data.uploadInfo.private_file_max_size}
          accept={fileTypes}
          loading={$loading}
          upload={handleUpload}
          remove={handleRemove}
          on:submit={handleSubmit}
        />
        <input type="hidden" name="assistant_id" bind:value={$assistant.id} />
        <input type="hidden" name="parties" bind:value={parties} />
      </div>
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
