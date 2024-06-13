<script lang="ts">
  import { goto } from '$app/navigation';
  import { navigating, page } from '$app/stores';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import {
    Button,
    Helper,
    Dropdown,
    DropdownItem,
    Span,
    Heading,
    Badge,
    DropdownDivider
  } from 'flowbite-svelte';
  import { EyeSlashOutline, ChevronDownSolid, ArrowRightOutline } from 'flowbite-svelte-icons';
  import { sadToast } from '$lib/toast';
  import * as api from '$lib/api';
  import { errorMessage } from '$lib/errors';
  import type { Assistant } from '$lib/api';
  import { onMount } from 'svelte';
  import { loading } from '$lib/stores/general';

  /**
   * Application data.
   */
  export let data;

  onMount(async () => {
    // Make sure that an assistant is linked in the URL
    if (!$page.url.searchParams.has('assistant')) {
      if (data.assistants.length > 0) {
        // replace current URL with one that has the assistant ID
        await goto(`/class/${data.class.id}/?assistant=${data.assistants[0].id}`, {
          replaceState: true
        });
      }
    }
  });

  // Get info about assistant provenance
  const getAssistantMetadata = (assistant: Assistant) => {
    const isCourseAssistant = assistant.endorsed;
    const isMyAssistant = assistant.creator_id === data.me.user!.id;
    const creator = data.assistantCreators[assistant.creator_id]?.name || 'Unknown creator';
    return {
      creator: isCourseAssistant ? 'Teaching Team' : creator,
      isCourseAssistant,
      isMyAssistant
    };
  };

  // Currently selected assistant.
  $: assistants = data?.assistants || [];
  $: courseAssistants = assistants.filter((asst) => asst.endorsed);
  $: otherAssistants = assistants.filter((asst) => !asst.endorsed);
  $: assistant = data?.assistants[0] || {};
  $: assistantMeta = getAssistantMetadata(assistant);
  // Whether billing is set up for the class (which controls everything).
  $: isConfigured = data?.hasAssistants && data?.hasBilling;
  $: parties = data.me.user?.id ? `${data.me.user.id}` : '';
  // The assistant ID from the URL.
  $: linkedAssistant = parseInt($page.url.searchParams.get('assistant') || '0', 10);
  $: {
    if (linkedAssistant && assistants) {
      const selectedAssistant = (assistants || []).find((asst) => asst.id === linkedAssistant);
      if (selectedAssistant) {
        assistant = selectedAssistant;
      }
    }
  }
  $: fileTypes = data.uploadInfo.fileTypesForAssistants(assistant);

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
          assistant_id: assistant.id,
          parties: partyIds,
          message: form.message,
          file_ids: form.file_ids
        })
      );
      data.threads = [newThread, ...data.threads];
      $loading = false;
      await goto(`/class/${$page.params.classId}/thread/${newThread.id}`);
    } catch (e) {
      sadToast(`Failed to create thread. Error: ${errorMessage(e)}`);
      $loading = false;
    }
  };

  // Set the new assistant selection.
  const selectAi = async (asst: Assistant) => {
    await goto(`/class/${data.class.id}/?assistant=${asst.id}`);
  };
</script>

<div class="flex justify-center relative min-h-0 grow shrink">
  <div
    class="w-11/12 transition-opacity ease-in flex flex-col h-full justify-between"
    class:opacity-0={$loading}
  >
    {#if isConfigured}
      <!-- Only show a picker if there are multiple assistants. -->
      {#if assistants.length > 1}
        <div class="pt-2 mt-4 relative flex items-center gap-2">
          <p class="eyebrow eyebrow-dark">Change Assistant</p>
          <Button
            pill
            class="bg-blue-light-50 text-xs uppercase tracking-wide font-medium text-black border-solid border border-blue-dark-40"
            >{assistant.name} <ChevronDownSolid class="w-3 h-3 ms-2" /></Button
          >

          <Dropdown class="max-h-60 overflow-y-auto w-60">
            <!-- Show course assistants first -->
            {#each courseAssistants as asst}
              <DropdownItem
                on:click={() => selectAi(asst)}
                on:touchstart={() => selectAi(asst)}
                class="uppercase tracking-wide font-medium"
              >
                {#if !asst.published}
                  <EyeSlashOutline size="sm" class="inline-block mr-2 text-gray-400" />
                {/if}
                {asst.name}
                <div>
                  <Badge class="bg-blue-light-50 mt-1 text-blue-dark-30 text-xs normal-case"
                    >Course assistant</Badge
                  >
                </div>
              </DropdownItem>
            {/each}

            <!-- Show a divider if necessary -->
            {#if otherAssistants.length > 0 && courseAssistants.length > 0}
              <DropdownDivider />
            {/if}

            <!-- Show non-course assistants -->
            {#each otherAssistants as asst}
              {@const meta = getAssistantMetadata(asst)}
              <DropdownItem
                on:click={() => selectAi(asst)}
                on:touchstart={() => selectAi(asst)}
                class="uppercase tracking-wide font-medium"
              >
                {#if !asst.published}
                  <EyeSlashOutline size="sm" class="inline-block mr-2 text-gray-400" />
                {/if}
                {asst.name}
                <div>
                  {#if meta.isCourseAssistant}
                    <Badge class="bg-blue-light-50 mt-1 text-blue-dark-30 text-xs normal-case"
                      >Course assistant</Badge
                    >
                  {:else if meta.isMyAssistant}
                    <Badge class="bg-blue-light-50 mt-1 text-blue-dark-30 text-xs normal-case"
                      >My assistant</Badge
                    >
                  {:else}
                    <Badge class="bg-blue-light-50 mt-1 text-blue-dark-30 text-xs normal-case"
                      >{meta.creator}</Badge
                    >
                  {/if}
                </div>
              </DropdownItem>
            {/each}
          </Dropdown>
        </div>
      {/if}

      <div class="relative bg-blue-light-40 rounded-2xl my-8 max-w-md mb-auto">
        <div class="min-h-0 overflow-y-auto bg-blue-light-50 p-6 rounded-2xl">
          <div>
            <p class="eyebrow eyebrow-dark">Current assistant</p>
            <Heading tag="h3" class="font-normal tracking-wide text-3xl mb-1"
              >{assistant.name}</Heading
            >
          </div>
          <div class="mb-6">
            {#if assistantMeta.isCourseAssistant}
              <Badge class="bg-blue-light-40 mt-1 text-blue-dark-30 text-xs normal-case"
                >Course assistant</Badge
              >
            {:else if assistantMeta.isMyAssistant}
              <Badge class="bg-blue-light-40 mt-1 text-blue-dark-30 text-xs normal-case"
                >My assistant</Badge
              >
            {:else}
              <Badge class="bg-blue-light-40 mt-1 text-blue-dark-30 text-xs normal-case"
                >{assistantMeta.creator}</Badge
              >
            {/if}
          </div>
          {#if assistant.description}
            <div class="dark:text-white text-gray-500 eyebrow eyebrow-dark">
              Notes for this assistant
            </div>
            <div class="pb-12 overflow-y-auto">{assistant.description}</div>
          {:else}
            <div class="italic">No notes are provided for this assistant.</div>
          {/if}
        </div>
        <div class="absolute bottom-5 right-4">
          <a
            href={`/class/${data.class.id}/assistant`}
            class="bg-orange-light text-orange-dark rounded rounded-2xl p-2 text-xs px-4 pr-2 hover:bg-orange-dark hover:text-orange-light transition-all"
            >View all assistants <ArrowRightOutline
              size="md"
              class="text-orange-dark inline-block ml-1"
            /></a
          >
        </div>
      </div>

      <div class="shrink-0 grow-0">
        <ChatInput
          mimeType={data.uploadInfo.mimeType}
          maxSize={data.uploadInfo.private_file_max_size}
          accept={fileTypes}
          loading={$loading || !!$navigating}
          upload={handleUpload}
          remove={handleRemove}
          on:submit={handleSubmit}
        />
        <div class="flex gap-2 px-4 py-2 items-center w-full text-sm flex-wrap lg:flex-nowrap">
          <EyeSlashOutline size="sm" class="text-orange" />
          <Span class="text-gray-400 text-xs"
            >This thread will be visible to yourself and the teaching team.</Span
          >
        </div>
        <input type="hidden" name="assistant_id" bind:value={assistant.id} />
        <input type="hidden" name="parties" bind:value={parties} />
      </div>
    {:else}
      <div class="text-center m-auto">
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
