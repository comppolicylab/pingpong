<script lang="ts">
  import { page } from '$app/stores';
  import { copy } from 'svelte-copy';
  import {
    Button,
    Heading,
    Label,
    Input,
    Modal,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    Tooltip,
    Select
  } from 'flowbite-svelte';
  import {
    EyeOutline,
    EyeSlashOutline,
    LinkOutline,
    PenSolid,
    CirclePlusSolid,
    GlobeOutline,
    PlusOutline,
    FileCopyOutline,
    TrashBinOutline,
    CheckCircleOutline,
    ExclamationCircleOutline
  } from 'flowbite-svelte-icons';
  import ConfirmationModal from '$lib/components/ConfirmationModal.svelte';
  import type { Assistant, AppUser } from '$lib/api';
  import dayjs from 'dayjs';
  import { happyToast, sadToast } from '$lib/toast';
  import * as api from '$lib/api';
  import { resolve } from '$app/paths';
  import {
    checkCopyPermission as sharedCheckCopyPermission,
    defaultCopyName,
    parseTargetClassId,
    performCopyAssistant,
    performDeleteAssistant
  } from '$lib/assistantHelpers';
  import { invalidateAll } from '$app/navigation';
  import { loading, loadingMessage } from '$lib/stores/general';

  export let assistant: Assistant;
  export let creator: AppUser;
  export let editable = false;
  export let shareable = false;
  export let classOptions: { id: number; name: string; term: string }[] = [];
  export let currentClassId: number;

  let sharedAssistantModalOpen = false;
  let copyAssistantModalOpen = false;
  let deleteAssistantModalOpen = false;
  let copyName = '';
  let copyTargetClassId = `${currentClassId}`;
  let copyPermissionAllowed: boolean | undefined = undefined;
  let copyPermissionLoading = false;
  let copyPermissionError = '';

  // Get the full URL to use the assistant
  $: assistantLink = `${$page.url.protocol}//${$page.url.host}/group/${assistant.class_id}?assistant=${assistant.id}`;
  $: sharedAssistantLinkWithParam = `${$page.url.protocol}//${$page.url.host}/group/${assistant.class_id}/shared/assistant/${assistant.id}?share_token=`;

  $: currentlyShared = assistant.share_links?.some((link) => link.active);
  $: shareLinks = assistant.share_links || [];

  // Show info that we copied the link to the clipboard
  const showCopiedLink = (e: Event) => {
    e.preventDefault();
    e.stopPropagation();
    happyToast('Link copied to clipboard', 3000);
  };

  const checkCopyPermission = async (targetClassId: string) => {
    const targetId = parseTargetClassId(targetClassId, currentClassId);
    if (targetId === null) {
      copyPermissionAllowed = false;
      copyPermissionError = 'Invalid class selected.';
      return;
    }
    copyPermissionLoading = true;
    copyPermissionError = '';
    const result = await sharedCheckCopyPermission(
      fetch,
      assistant.class_id,
      assistant.id,
      targetId
    );
    copyPermissionAllowed = result.allowed;
    copyPermissionError = result.error;
    copyPermissionLoading = false;
  };

  const createLink = async () => {
    const result = await api.createAssistantShareLink(fetch, assistant.class_id, assistant.id);
    const expanded = api.expandResponse(result);
    if (expanded.error) {
      return sadToast(`Failed to create shared link: ${expanded.error.detail}`);
    }

    happyToast('Shared link created successfully', 3000);
    await invalidateAll();
  };

  const submitInputForm = async (e: Event, link_id: number) => {
    e.preventDefault();
    e.stopPropagation();
    const target = e.target as HTMLInputElement;
    const name = target.value.trim();

    const result = await api.updateAssistantShareLinkName(
      fetch,
      assistant.class_id,
      assistant.id,
      link_id,
      { name }
    );
    const expanded = api.expandResponse(result);
    if (expanded.error) {
      return sadToast(`Failed to update shared link: ${expanded.error.detail}`);
    }
    happyToast('Shared link updated successfully', 2000);
  };

  const deleteLink = async (link_id: number) => {
    const result = await api.deleteAssistantShareLink(
      fetch,
      assistant.class_id,
      assistant.id,
      link_id
    );
    const expanded = api.expandResponse(result);
    if (expanded.error) {
      return sadToast(`Failed to deactivate shared link: ${expanded.error.detail}`);
    }
    happyToast('Shared link deactivated successfully', 2000);
    await invalidateAll();
  };

  const copyAssistant = async () => {
    if (copyPermissionLoading) {
      return sadToast('Please wait while we check permissions.');
    }
    if (!copyPermissionAllowed) {
      return sadToast(copyPermissionError || "You don't have permission to copy to that group.");
    }
    $loadingMessage = 'Copying assistant...';
    $loading = true;
    const result = await performCopyAssistant(fetch, assistant.class_id, assistant.id, {
      name: copyName,
      fallbackName: assistant.name,
      targetClassId: copyTargetClassId
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
    copyAssistantModalOpen = false;
  };

  const deleteAssistant = async () => {
    deleteAssistantModalOpen = false;
    $loadingMessage = 'Deleting assistant...';
    $loading = true;
    const result = await performDeleteAssistant(fetch, assistant.class_id, assistant.id);
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
</script>

<Modal size="xl" bind:open={sharedAssistantModalOpen}>
  <slot name="header">
    <Heading
      tag="h2"
      class="text-3xl font-serif font-medium text-blue-dark-40 shrink-0 max-w-max mr-5 mb-4"
      color="blue">Manage Shared Links</Heading
    >
  </slot>
  <div class="flex flex-row flex-wrap justify-between mb-4 items-center gap-y-4 text-blue-dark-50">
    <Button
      pill
      size="sm"
      class="flex flex-row gap-2 bg-white text-blue-dark-40 border-solid border border-blue-dark-40 hover:text-white hover:bg-blue-dark-40"
      onclick={createLink}><PlusOutline />New Shared Link</Button
    >
  </div>

  <div>
    <Table class="w-full">
      <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
        <TableHeadCell>Description</TableHeadCell>
        <TableHeadCell>Status</TableHeadCell>
        <TableHeadCell>Last Updated</TableHeadCell>
        <TableHeadCell></TableHeadCell>
      </TableHead>
      <TableBody>
        {#each shareLinks as link (link.id)}
          <TableBodyRow>
            <TableBodyCell class="py-2 font-medium whitespace-normal"
              ><Input
                id="name"
                name="name"
                value={link.name}
                placeholder="Shared Link"
                onchange={(e) => submitInputForm(e, link.id)}
              /></TableBodyCell
            >
            <TableBodyCell
              class="py-2 font-normal whitespace-normal uppercase text-sm font-semibold {!link.active
                ? 'text-gray-700'
                : 'text-green-700'}"
            >
              {link.active ? 'Active' : 'Inactive'}
            </TableBodyCell>
            <TableBodyCell class="py-2 font-normal whitespace-normal">
              {link.revoked_at
                ? dayjs.utc(link.revoked_at).fromNow()
                : link.activated_at
                  ? dayjs.utc(link.activated_at).fromNow()
                  : ''}
            </TableBodyCell>

            <TableBodyCell class="py-2">
              <div class="flex flex-row gap-2">
                <button
                  class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
                  onclick={(event) => {
                    event.preventDefault();
                  }}
                  oncopy={showCopiedLink}
                  use:copy={`${sharedAssistantLinkWithParam}${link.share_token}`}
                >
                  <LinkOutline class="inline-block w-4 h-4" />
                  Copy Link
                </button>
                {#if link.active}
                  <Button
                    pill
                    size="sm"
                    class="text-xs border border-gray-800 text-green-800 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-gray-800 transition-all w-fit"
                    disabled={!link.active}
                    onclick={() => deleteLink(link.id)}
                  >
                    Disable Link
                  </Button>
                {/if}
              </div>
            </TableBodyCell>
          </TableBodyRow>
        {/each}
      </TableBody>
    </Table>
  </div>
</Modal>

<div
  class="flex flex-col gap-2 {editable
    ? 'bg-gold-light'
    : 'bg-orange-light'} rounded-2xl px-8 pt-6 py-4 pr-4 pb-8"
>
  <Heading tag="h3" class="flex gap-4 text-3xl font-normal items-center">
    <div class="flex flex-row items-center gap-3">
      {assistant.name}
      <div class="flex flex-row items-center gap-1">
        {#if !assistant.published}
          <EyeSlashOutline class="inline-block w-5 h-5 mr-1 text-gray-500" />
          <Tooltip placement="top" class="text-xs font-light"
            >This assistant is not currently published.</Tooltip
          >
        {:else}
          <EyeOutline class="inline-block w-5 h-5 mr-1 text-orange" />
          <Tooltip placement="top" class="text-xs font-light"
            >This assistant is currently published and available to all members.</Tooltip
          >
        {/if}
        {#if currentlyShared}
          <GlobeOutline class="inline-block w-5 h-5 mr-1 text-orange" />
          <Tooltip placement="top" class="text-xs font-light"
            >One or more sharable links are active for this assistant.</Tooltip
          >
        {/if}
      </div>
    </div>

    <div class="ml-auto flex shrink-0 items-center gap-2">
      {#if editable}
        <button
          class="text-blue-dark-30 hover:text-blue-dark-50"
          aria-label="Copy assistant"
          onclick={(event) => {
            event.preventDefault();
            copyName = defaultCopyName(assistant.name);
            copyTargetClassId = `${currentClassId}`;
            copyPermissionAllowed = false;
            copyPermissionLoading = false;
            copyPermissionError = '';
            checkCopyPermission(copyTargetClassId);
            copyAssistantModalOpen = true;
          }}><FileCopyOutline size="md" /></button
        >
        <button
          class="text-blue-dark-30 hover:text-blue-dark-50"
          aria-label="Delete assistant"
          onclick={(event) => {
            event.preventDefault();
            deleteAssistantModalOpen = true;
          }}><TrashBinOutline size="md" /></button
        >
        <a
          class="text-blue-dark-30 hover:text-blue-dark-50"
          href={resolve(`/group/${assistant.class_id}/assistant/${assistant.id}`)}
          ><PenSolid size="md" /></a
        >
      {/if}

      <button onclick={() => {}} oncopy={showCopiedLink} use:copy={assistantLink}
        ><LinkOutline
          class="inline-block w-6 h-6 text-blue-dark-30 hover:text-blue-dark-50 active:animate-ping"
        /></button
      >

      {#if editable && shareable && assistant.published}
        <button
          onclick={(event) => {
            event.preventDefault();
            sharedAssistantModalOpen = true;
          }}
          ><GlobeOutline
            class="inline-block w-6 h-6 text-blue-dark-30 hover:text-blue-dark-50 active:animate-ping"
          /></button
        >
      {/if}
    </div>
  </Heading>
  <div class="text-xs mb-4">Created by <b>{creator.name}</b></div>
  <div class="mb-4 font-light max-h-24 overflow-y-auto">
    {assistant.description || '(No description provided)'}
  </div>
  <div>
    <!-- eslint-disable svelte/no-navigation-without-resolve -->
    <a
      href={assistantLink}
      class="flex items-center w-36 gap-2 text-sm text-white font-medium bg-orange rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
      >Start a chat <CirclePlusSolid size="sm" class="inline" /></a
    >
    <!-- eslint-enable svelte/no-navigation-without-resolve -->
  </div>
</div>

<Modal
  size="md"
  bind:open={copyAssistantModalOpen}
  onclose={() => (copyAssistantModalOpen = false)}
>
  <slot name="header">
    <Heading tag="h3" class="text-2xl font-serif font-medium text-blue-dark-40"
      >Copy Assistant</Heading
    >
  </slot>
  <p class="mb-4 text-blue-dark-40">
    This will create a private copy of <b>{assistant.name}</b> in the group you select. You can rename
    it below.
  </p>
  <div class="mb-6">
    <Label for="copy-name" class="mb-1 block text-sm font-medium text-blue-dark-50"
      >New Assistant Name</Label
    >
    <Input
      id="copy-name"
      name="copy-name"
      bind:value={copyName}
      placeholder={defaultCopyName(assistant.name)}
    />
  </div>
  <div class="mb-6">
    <div class="mt-2 flex items-center justify-between text-sm text-blue-dark-50 mb-1">
      <Label for={`copy-target-${assistant.id}`} class="block text-sm font-medium text-blue-dark-50"
        >Copy to...</Label
      >

      {#if copyPermissionLoading}
        <span class="italic text-gray-500">Checking permissions...</span>
      {:else if copyPermissionAllowed === true}
        <span class="flex items-center gap-1 text-green-700">
          <CheckCircleOutline class="w-4 h-4" /> Can create assistant in this Group
        </span>
      {:else}
        <span class="flex items-center gap-1 text-red-700">
          <ExclamationCircleOutline class="w-4 h-4" />
          {copyPermissionError || "Can't create assistant in this Group"}
        </span>
      {/if}
    </div>
    <Select
      id={`copy-target-${assistant.id}`}
      name={`copy-target-${assistant.id}`}
      bind:value={copyTargetClassId}
      size="md"
      class="w-full"
      onchange={() => checkCopyPermission(copyTargetClassId)}
    >
      {#each classOptions as option (option.id)}
        <option value={`${option.id}`}>
          {option.term ? `${option.name} (${option.term})` : option.name}
        </option>
      {/each}
    </Select>
  </div>
  <div class="flex gap-3 justify-end">
    <Button color="light" onclick={() => (copyAssistantModalOpen = false)}>Cancel</Button>
    <Button
      color="blue"
      disabled={copyPermissionLoading || copyPermissionAllowed !== true}
      onclick={copyAssistant}>Copy</Button
    >
  </div>
</Modal>

<Modal bind:open={deleteAssistantModalOpen} size="xs" autoclose>
  <ConfirmationModal
    warningTitle={`Delete ${assistant?.name || 'this assistant'}?`}
    warningDescription="All threads associated with this assistant will become read-only."
    warningMessage="This action cannot be undone."
    cancelButtonText="Cancel"
    confirmText="delete"
    confirmButtonText="Delete assistant"
    on:cancel={() => (deleteAssistantModalOpen = false)}
    on:confirm={deleteAssistant}
  />
</Modal>
