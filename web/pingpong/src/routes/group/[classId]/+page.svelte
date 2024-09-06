<script lang="ts">
  import { goto } from '$app/navigation';
  import { navigating, page } from '$app/stores';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import {
    Button,
    Dropdown,
    DropdownItem,
    Span,
    Heading,
    Badge,
    DropdownDivider
  } from 'flowbite-svelte';
  import {
    EyeSlashOutline,
    ChevronDownOutline,
    ArrowRightOutline,
    LockSolid
  } from 'flowbite-svelte-icons';
  import { sadToast } from '$lib/toast';
  import * as api from '$lib/api';
  import { errorMessage } from '$lib/errors';
  import type { Assistant, FileUploadPurpose } from '$lib/api';
  import { onMount } from 'svelte';
  import { loading } from '$lib/stores/general';

  /**
   * Application data.
   */
  export let data;

  const errorMessages: Record<number, string> = {
    1: 'We faced an issue when trying to sync with Canvas.'
  };

  // Function to get error message from error code
  function getErrorMessage(errorCode: number) {
    return (
      errorMessages[errorCode] || 'An unknown error occurred while trying to sync with Canvas.'
    );
  }

  onMount(async () => {
    const errorCode = $page.url.searchParams.get('error_code');
    if (errorCode) {
      const errorMessage = getErrorMessage(parseInt(errorCode) || 0);
      sadToast(errorMessage);
    }
    // Make sure that an assistant is linked in the URL
    if (!$page.url.searchParams.has('assistant')) {
      if (data.assistants.length > 0) {
        // replace current URL with one that has the assistant ID
        await goto(`/group/${data.class.id}/?assistant=${data.assistants[0].id}`, {
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
      creator: isCourseAssistant ? 'Moderation Team' : creator,
      isCourseAssistant,
      isMyAssistant
    };
  };

  $: isPrivate = data.class.private || false;
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
  $: supportsFileSearch = assistant.tools?.includes('file_search') || false;
  $: supportsCodeInterpreter = assistant.tools?.includes('code_interpreter') || false;
  let supportsVision = false;
  $: {
    const supportVisionModels = (data.models.filter((model) => model.supports_vision) || []).map(
      (model) => model.id
    );
    supportsVision = supportVisionModels.includes(assistant.model);
  }
  $: allowVisionUpload = true;

  // Handle file upload
  const handleUpload = (
    f: File,
    onProgress: (p: number) => void,
    purpose: FileUploadPurpose = 'assistants'
  ) => {
    return api.uploadUserFile(data.class.id, data.me.user!.id, f, { onProgress }, purpose);
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
    const tools: api.Tool[] = [];
    if (supportsFileSearch) {
      tools.push({ type: 'file_search' });
    }
    if (supportsCodeInterpreter) {
      tools.push({ type: 'code_interpreter' });
    }

    try {
      const newThread = api.explodeResponse(
        await api.createThread(fetch, data.class.id, {
          assistant_id: assistant.id,
          parties: partyIds,
          message: form.message,
          tools_available: tools,
          code_interpreter_file_ids: form.code_interpreter_file_ids,
          file_search_file_ids: form.file_search_file_ids,
          vision_file_ids: form.vision_file_ids
        })
      );
      data.threads = [newThread as api.Thread, ...data.threads];
      $loading = false;
      await goto(`/group/${$page.params.classId}/thread/${newThread.id}`);
    } catch (e) {
      sadToast(`Failed to create thread. Error: ${errorMessage(e)}`);
      $loading = false;
    }
  };

  // Set the new assistant selection.
  const selectAi = async (asst: Assistant) => {
    await goto(`/group/${data.class.id}/?assistant=${asst.id}`);
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
            >{assistant.name} <ChevronDownOutline class="w-3 h-3 ms-2" /></Button
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
                >Group assistant</Badge
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
          {/if}
        </div>
        {#if assistants.length > 1}
          <div class="absolute bottom-5 right-4">
            <a
              href={`/group/${data.class.id}/assistant`}
              class="bg-orange-light text-orange-dark rounded rounded-2xl p-2 text-xs px-4 pr-2 hover:bg-orange-dark hover:text-orange-light transition-all"
              >View all assistants <ArrowRightOutline
                size="md"
                class="text-orange-dark inline-block ml-1"
              /></a
            >
          </div>
        {/if}
      </div>

      <div class="shrink-0 grow-0">
        <ChatInput
          mimeType={data.uploadInfo.mimeType}
          maxSize={data.uploadInfo.private_file_max_size}
          loading={$loading || !!$navigating}
          canSubmit={true}
          visionAcceptedFiles={supportsVision && allowVisionUpload
            ? data.uploadInfo.fileTypes({
                file_search: false,
                code_interpreter: false,
                vision: true
              })
            : null}
          fileSearchAcceptedFiles={supportsFileSearch
            ? data.uploadInfo.fileTypes({
                file_search: true,
                code_interpreter: false,
                vision: false
              })
            : null}
          codeInterpreterAcceptedFiles={supportsCodeInterpreter
            ? data.uploadInfo.fileTypes({
                file_search: false,
                code_interpreter: true,
                vision: false
              })
            : null}
          upload={handleUpload}
          remove={handleRemove}
          on:submit={handleSubmit}
        />
        {#if isPrivate}
          <div class="flex gap-2 px-4 py-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
            <LockSolid size="sm" class="text-orange pt-0" />
            <Span class="text-gray-400 text-xs font-normal"
              >Moderators <span class="font-semibold">cannot</span> see this thread or your name.
              For more information, please review
              <a href="/privacy-policy" rel="noopener noreferrer" class="underline"
                >PingPong's privacy statement</a
              >. Assistants can make mistakes. Check important info.</Span
            >
          </div>
        {:else}
          <div class="flex gap-2 px-4 py-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
            <EyeSlashOutline size="sm" class="text-orange pt-0" />
            <Span class="text-gray-400 text-xs font-normal"
              >Moderators can see this thread but not your name. For more information, please review <a
                href="/privacy-policy"
                rel="noopener noreferrer"
                class="underline">PingPong's privacy statement</a
              >. Assistants can make mistakes. Check important info.</Span
            >
          </div>
        {/if}
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
          <h1 class="text-2xl font-bold">Group is not configured.</h1>
        {/if}
      </div>
    {/if}
  </div>
</div>
