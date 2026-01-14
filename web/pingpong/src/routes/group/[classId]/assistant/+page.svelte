<script lang="ts">
  import { resolve } from '$app/paths';
  import type { Assistant } from '$lib/api';
  import ViewAssistant from '$lib/components/ViewAssistant.svelte';
  import {
    Heading,
    Button,
    Input,
    Label,
    Modal,
    Select,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell
  } from 'flowbite-svelte';
  import {
    ArrowRightOutline,
    CirclePlusSolid,
    LinkOutline,
    PenSolid,
    FileCopyOutline,
    TrashBinOutline,
    CheckCircleOutline,
    ExclamationCircleOutline
  } from 'flowbite-svelte-icons';
  import ConfirmationModal from '$lib/components/ConfirmationModal.svelte';
  import { happyToast, sadToast } from '$lib/toast';
  import { copy } from 'svelte-copy';
  import { loading, loadingMessage } from '$lib/stores/general';
  import { invalidateAll } from '$app/navigation';
  import {
    checkCopyPermission as sharedCheckCopyPermission,
    defaultCopyName,
    parseTargetClassId,
    performCopyAssistant,
    performDeleteAssistant
  } from '$lib/assistantHelpers';

  export let data;

  $: hasApiKey = !!data?.hasAPIKey;
  $: creators = data?.assistantCreators || {};
  $: moderators = data?.supervisors || [];
  // "Course" assistants are endorsed by the class. Right now this means
  // they are created by the teaching team and are published.
  let courseAssistants: Assistant[] = [];
  // "My" assistants are assistants created by the current user, except
  // for those that appear in "course" assistants.
  let myAssistants: Assistant[] = [];
  // "Other" assistants are non-endorsed assistants that are not created by the current user.
  // For most people this means published assistants from other students. For people with
  // elevated permissions, this could also mean private assistants.
  let otherAssistants: Assistant[] = [];
  let copyModalState: Record<number, boolean> = {};
  let deleteModalState: Record<number, boolean> = {};
  let copyNames: Record<number, string> = {};
  let copyTargets: Record<number, string> = {};
  let copyPermissionAllowed: Record<number, boolean> = {};
  let copyPermissionLoading: Record<number, boolean> = {};
  let copyPermissionError: Record<number, string> = {};
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : '';
  const classOptions = (data.classes || []).map((c) => ({
    id: c.id,
    name: c.name,
    term: c.term
  }));
  const assistantLink = (assistantId: number) =>
    `${baseUrl}/group/${data.class.id}?assistant=${assistantId}`;

  const openCopyModal = (assistantId: number, name: string) => {
    copyModalState = { ...copyModalState, [assistantId]: true };
    copyNames = { ...copyNames, [assistantId]: defaultCopyName(name) };
    copyTargets = { ...copyTargets, [assistantId]: `${data.class.id}` };
    copyPermissionAllowed = { ...copyPermissionAllowed, [assistantId]: true };
    copyPermissionLoading = { ...copyPermissionLoading, [assistantId]: false };
    copyPermissionError = { ...copyPermissionError, [assistantId]: '' };
    void checkCopyPermission(assistantId, `${data.class.id}`);
  };

  const closeCopyModal = (assistantId: number) => {
    copyModalState = { ...copyModalState, [assistantId]: false };
  };

  const openDeleteModal = (assistantId: number) => {
    deleteModalState = { ...deleteModalState, [assistantId]: true };
  };

  const closeDeleteModal = (assistantId: number) => {
    deleteModalState = { ...deleteModalState, [assistantId]: false };
  };

  const handleCopyAssistant = async (assistantId: number) => {
    if (copyPermissionLoading[assistantId]) {
      return sadToast('Please wait while we check permissions.');
    }
    if (copyPermissionAllowed[assistantId] !== true) {
      return sadToast(
        copyPermissionError[assistantId] || "You don't have permission to copy to that group."
      );
    }
    const fallbackName =
      otherAssistants.find((a) => a.id === assistantId)?.name ||
      courseAssistants.find((a) => a.id === assistantId)?.name ||
      myAssistants.find((a) => a.id === assistantId)?.name ||
      'Assistant';
    const name = (copyNames[assistantId] || '').trim() || defaultCopyName(fallbackName);
    $loadingMessage = 'Copying assistant...';
    $loading = true;
    const result = await performCopyAssistant(fetch, data.class.id, assistantId, {
      name,
      fallbackName: fallbackName,
      targetClassId: copyTargets[assistantId]
    });
    if (result.error) {
      $loadingMessage = '';
      $loading = false;
      const detail =
        (result.error as Error & { detail?: string }).detail ||
        (result.error as Error).message ||
        'Unknown error';
      return sadToast(`Failed to copy assistant: ${detail}`);
    }
    happyToast('Assistant copied', 2000);
    await invalidateAll();
    $loadingMessage = '';
    $loading = false;
    closeCopyModal(assistantId);
  };

  const handleDeleteAssistant = async (assistantId: number) => {
    closeDeleteModal(assistantId);
    $loadingMessage = 'Deleting assistant...';
    $loading = true;
    const result = await performDeleteAssistant(fetch, data.class.id, assistantId);
    if (result.error) {
      $loadingMessage = '';
      $loading = false;
      const detail =
        (result.error as Error & { detail?: string }).detail ||
        (result.error as Error).message ||
        'Unknown error';
      return sadToast(`Error deleting assistant: ${detail}`);
    }
    happyToast('Assistant deleted');
    await invalidateAll();
    $loadingMessage = '';
    $loading = false;
  };

  const showCopiedLink = (e: Event) => {
    e.preventDefault();
    e.stopPropagation();
    happyToast('Link copied to clipboard', 2000);
  };

  const updateCopyName = (assistantId: number, value: string) => {
    copyNames = { ...copyNames, [assistantId]: value };
  };

  const handleCopyNameInput = (assistantId: number, event: Event) => {
    const target = event.target as HTMLInputElement;
    updateCopyName(assistantId, target?.value || '');
  };

  const updateCopyTarget = (assistantId: number, value: string) => {
    copyTargets = { ...copyTargets, [assistantId]: value };
  };

  const checkCopyPermission = async (assistantId: number, targetClassId: string) => {
    const targetId = parseTargetClassId(targetClassId, data.class.id);
    if (targetId === null) {
      copyPermissionAllowed = { ...copyPermissionAllowed, [assistantId]: false };
      copyPermissionError = { ...copyPermissionError, [assistantId]: 'Invalid class selected.' };
      return;
    }
    copyPermissionLoading = { ...copyPermissionLoading, [assistantId]: true };
    copyPermissionError = { ...copyPermissionError, [assistantId]: '' };
    const result = await sharedCheckCopyPermission(fetch, data.class.id, assistantId, targetId);
    copyPermissionAllowed = { ...copyPermissionAllowed, [assistantId]: result.allowed };
    copyPermissionError = { ...copyPermissionError, [assistantId]: result.error };
    copyPermissionLoading = { ...copyPermissionLoading, [assistantId]: false };
  };

  const handleCopyTargetSelect = (assistantId: number, event: Event) => {
    const target = event.target as HTMLSelectElement;
    const value = target?.value || '';
    updateCopyTarget(assistantId, value);
    void checkCopyPermission(assistantId, value);
  };
  $: {
    const allAssistants = data?.assistants || [];
    // Split all assistants into categories
    courseAssistants = allAssistants.filter((assistant) => assistant.endorsed);
    myAssistants = allAssistants.filter(
      (assistant) => assistant.creator_id === data.me.user!.id && !assistant.endorsed
    );
    otherAssistants = allAssistants.filter(
      (assistant) => assistant.creator_id !== data.me.user!.id && !assistant.endorsed
    );
  }
</script>

<div class="h-full w-full overflow-y-auto p-12">
  {#if !hasApiKey}
    <Heading tag="h2" class="font-serif mb-4 font-medium text-3xl text-dark-blue-40"
      >No API key.</Heading
    >
    <div>You must configure an API key for this group before you can create or use assistants.</div>
  {:else}
    {#if data.grants.canCreateAssistants}
      <Heading tag="h2" class="text-3xl font-serif mb-4 font-medium text-dark-blue-40"
        >Make a new assistant</Heading
      >
      <div class="bg-gold rounded-2xl p-8 mb-12 justify-between gap-12 items-start lg:flex">
        <p class="font-light">
          Build your own AI chatbot for this group. You can customize it with specific knowledge,
          personality, and parameters to serve as a digital assistant for this group.
        </p>
        <a
          href={resolve(`/group/${data.class.id}/assistant/new`)}
          class="text-sm text-blue-dark-50 shrink-0 flex items-center justify-center font-medium bg-white rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
          >Create new assistant <ArrowRightOutline size="md" class="orange inline-block" /></a
        >
      </div>
    {/if}

    <Heading tag="h2" class="text-3xl font-serif mb-4 font-medium text-dark-blue-40"
      >Your assistants</Heading
    >
    <div class="grid md:grid-cols-2 gap-4 mb-12">
      {#each myAssistants as assistant (assistant.id)}
        <ViewAssistant
          {assistant}
          creator={creators[assistant.creator_id]}
          editable={data.editableAssistants.has(assistant.id)}
          currentClassId={data.class.id}
          {classOptions}
        />
      {:else}
        <div>No assistants</div>
      {/each}
    </div>

    <Heading tag="h2" class="text-3xl font-serif font-medium mb-4 text-dark-blue-40"
      >Group assistants</Heading
    >
    <div class="grid md:grid-cols-2 gap-4 mb-12">
      {#each courseAssistants as assistant (assistant.id)}
        <ViewAssistant
          {assistant}
          creator={creators[assistant.creator_id]}
          editable={data.editableAssistants.has(assistant.id)}
          shareable={data.grants.canShareAssistants && !!assistant.published}
          currentClassId={data.class.id}
          {classOptions}
        />
      {:else}
        <div>No group assistants</div>
      {/each}
    </div>

    <Heading tag="h2" class="text-3xl font-serif font-medium mb-4 text-dark-blue-40"
      >Other assistants</Heading
    >
    {#if otherAssistants.length === 0}
      <div>No other assistants</div>
    {:else}
      <Table>
        <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
          <TableHeadCell>Assistant Name</TableHeadCell>
          <TableHeadCell>Author</TableHeadCell>
          <TableHeadCell>Status</TableHeadCell>
          <TableHeadCell>Chat</TableHeadCell>
          <TableHeadCell class="text-right">Actions</TableHeadCell>
        </TableHead>
        <TableBody>
          {#each otherAssistants as assistant (assistant.id)}
            <TableBodyRow>
              <TableBodyCell class="font-light">{assistant.name}</TableBodyCell>
              <TableBodyCell class="font-light"
                >{creators[assistant.creator_id]?.name || 'unknown'}</TableBodyCell
              >
              <TableBodyCell class="font-light"
                >{assistant.published ? 'Published' : 'Private'}</TableBodyCell
              >
              <TableBodyCell
                ><a
                  href={resolve(`/group/${data.class.id}?assistant=${assistant.id}`)}
                  class="flex items-center w-32 gap-2 text-sm text-white font-medium bg-orange rounded-full p-1 px-3 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
                  >Start a chat <CirclePlusSolid size="sm" class="inline" /></a
                ></TableBodyCell
              >
              <TableBodyCell>
                <div class="flex flex-wrap gap-2 justify-end">
                  <button
                    class="text-blue-dark-40 hover:text-blue-dark-100"
                    aria-label="Copy assistant link"
                    onclick={() => {}}
                    oncopy={showCopiedLink}
                    use:copy={assistantLink(assistant.id)}
                  >
                    <LinkOutline class="w-5 h-5" />
                  </button>
                  {#if data.editableAssistants.has(assistant.id)}
                    <a
                      href={resolve(`/group/${data.class.id}/assistant/${assistant.id}`)}
                      class="text-blue-dark-40 hover:text-blue-dark-100"
                      aria-label="Edit assistant"><PenSolid class="w-5 h-5" /></a
                    >
                    <button
                      class="text-blue-dark-40 hover:text-blue-dark-100"
                      aria-label="Copy assistant"
                      onclick={() => openCopyModal(assistant.id, assistant.name)}
                    >
                      <FileCopyOutline class="w-5 h-5" />
                    </button>
                    <button
                      class="text-red-700 hover:text-red-900"
                      aria-label="Delete assistant"
                      onclick={() => openDeleteModal(assistant.id)}
                    >
                      <TrashBinOutline class="w-5 h-5" />
                    </button>
                  {/if}
                </div>

                <Modal
                  open={!!copyModalState[assistant.id]}
                  size="md"
                  onclose={() => closeCopyModal(assistant.id)}
                >
                  <div class="text-left whitespace-normal break-words">
                    <Heading tag="h3" class="text-2xl font-serif font-medium text-blue-dark-40"
                      >Copy Assistant</Heading
                    >
                    <p class="mb-4 text-blue-dark-40 mt-3 break-words whitespace-normal">
                      This will create a private copy of <b>{assistant.name}</b> in the group you select.
                      You can rename it below.
                    </p>
                    <div class="mb-6">
                      <Label
                        for={`copy-name-${assistant.id}`}
                        class="mb-1 block text-sm font-medium text-blue-dark-50"
                        >New Assistant Name</Label
                      >
                      <Input
                        id={`copy-name-${assistant.id}`}
                        name={`copy-name-${assistant.id}`}
                        value={copyNames[assistant.id] || ''}
                        oninput={(event) => handleCopyNameInput(assistant.id, event)}
                        placeholder={defaultCopyName(assistant.name)}
                      />
                    </div>
                    <div class="mb-6">
                      <div
                        class="mt-2 flex items-center justify-between text-sm text-blue-dark-50 mb-1"
                      >
                        <Label
                          for={`copy-target-${assistant.id}`}
                          class="block text-sm font-medium text-blue-dark-50">Copy to...</Label
                        >

                        {#if copyPermissionLoading[assistant.id]}
                          <span class="italic text-gray-500">Checking permissions...</span>
                        {:else if copyPermissionAllowed[assistant.id] ?? true}
                          <span class="flex items-center gap-1 text-green-700">
                            <CheckCircleOutline class="w-4 h-4" /> Can create assistant in this Group
                          </span>
                        {:else}
                          <span class="flex items-center gap-1 text-red-700">
                            <ExclamationCircleOutline class="w-4 h-4" />
                            {copyPermissionError[assistant.id] ||
                              "Can't create assistant in this Group"}
                          </span>
                        {/if}
                      </div>

                      <Select
                        id={`copy-target-${assistant.id}`}
                        name={`copy-target-${assistant.id}`}
                        value={copyTargets[assistant.id] || ''}
                        onchange={(event) => handleCopyTargetSelect(assistant.id, event)}
                      >
                        {#each classOptions as option (option.id)}
                          <option value={`${option.id}`}>
                            {option.term ? `${option.name} (${option.term})` : option.name}
                          </option>
                        {/each}
                      </Select>
                    </div>
                    <div class="flex gap-3 justify-end">
                      <Button color="light" onclick={() => closeCopyModal(assistant.id)}
                        >Cancel</Button
                      >
                      <Button
                        color="blue"
                        disabled={copyPermissionLoading[assistant.id] ||
                          copyPermissionAllowed[assistant.id] !== true}
                        onclick={() => handleCopyAssistant(assistant.id)}>Copy</Button
                      >
                    </div>
                  </div>
                </Modal>

                <Modal
                  open={!!deleteModalState[assistant.id]}
                  size="xs"
                  autoclose
                  onclose={() => closeDeleteModal(assistant.id)}
                >
                  <ConfirmationModal
                    warningTitle={`Delete ${assistant?.name || 'this assistant'}?`}
                    warningDescription="All threads associated with this assistant will become read-only."
                    warningMessage="This action cannot be undone."
                    cancelButtonText="Cancel"
                    confirmText="delete"
                    confirmButtonText="Delete assistant"
                    on:cancel={() => closeDeleteModal(assistant.id)}
                    on:confirm={() => handleDeleteAssistant(assistant.id)}
                  />
                </Modal>
              </TableBodyCell>
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    {/if}
  {/if}
  <Heading tag="h2" class="text-3xl font-serif font-medium mt-12 mb-4 text-dark-blue-40"
    >Group Moderators</Heading
  >
  {#if moderators.length === 0}
    <div>No supervisors</div>
  {:else}
    <Table>
      <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
        <TableHeadCell>Moderator Name</TableHeadCell>
        <TableHeadCell>Email</TableHeadCell>
      </TableHead>
      <TableBody>
        {#each moderators as moderator (moderator.email)}
          <TableBodyRow>
            {#if moderator.name}
              <TableBodyCell class="font-light">{moderator.name}</TableBodyCell>
            {:else}
              <TableBodyCell class="font-light italic">No recorded name</TableBodyCell>
            {/if}
            <TableBodyCell class="font-light">{moderator.email}</TableBodyCell>
          </TableBodyRow>
        {/each}
      </TableBody>
    </Table>
  {/if}
</div>
