<script lang="ts">
  import { page } from '$app/stores';
  import { copy } from 'svelte-copy';
  import {
    Button,
    Heading,
    Input,
    Modal,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    Tooltip
  } from 'flowbite-svelte';
  import {
    EyeOutline,
    EyeSlashOutline,
    LinkOutline,
    PenSolid,
    CirclePlusSolid,
    GlobeOutline,
    PlusOutline
  } from 'flowbite-svelte-icons';
  import type { Assistant, AppUser } from '$lib/api';
  import dayjs from 'dayjs';
  import { happyToast, sadToast } from '$lib/toast';
  import * as api from '$lib/api';
  import { invalidateAll } from '$app/navigation';

  export let assistant: Assistant;
  export let creator: AppUser;
  export let editable = false;
  export let shareable = true;

  let sharedAssistantModalOpen = false;

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
      on:click={createLink}><PlusOutline />New Shared Link</Button
    >
  </div>

  <div>
    <Table class="w-full">
      <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
        <TableHeadCell>Description</TableHeadCell>
        <TableHeadCell>Status</TableHeadCell>
        <TableHeadCell>Created</TableHeadCell>
        <TableHeadCell>Disabled</TableHeadCell>
        <TableHeadCell>Share Token</TableHeadCell>
        <TableHeadCell></TableHeadCell>
      </TableHead>
      <TableBody>
        {#each shareLinks as link}
          <TableBodyRow>
            <TableBodyCell class="py-2 font-medium whitespace-normal"
              ><Input
                id="name"
                name="name"
                value={link.name}
                placeholder="Shared Link"
                on:change={(e) => submitInputForm(e, link.id)}
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
              {link.activated_at ? dayjs.utc(link.activated_at).fromNow() : ''}
            </TableBodyCell>
            <TableBodyCell class="py-2 font-normal whitespace-normal">
              {link.revoked_at ? dayjs.utc(link.revoked_at).fromNow() : ''}
            </TableBodyCell>
            <TableBodyCell class="py-2 font-normal whitespace-normal truncate ">
              <span class="text-blue-dark-50 font-mono text-sm"
                >{link.share_token
                  ? link.share_token.slice(0, 5) + '...' + link.share_token.slice(-5)
                  : '(No token)'}</span
              >
              <Tooltip placement="top" class="text-xs font-light"
                >{link.share_token || 'No share token available'}</Tooltip
              >
            </TableBodyCell>

            <TableBodyCell class="py-2">
              <div class="flex flex-row gap-2">
                <button
                  class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
                  on:click|preventDefault={() => {}}
                  on:svelte-copy={showCopiedLink}
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
                    on:click={() => deleteLink(link.id)}
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
        <a
          class="text-blue-dark-30 hover:text-blue-dark-50"
          href="/group/{assistant.class_id}/assistant/{assistant.id}"><PenSolid size="md" /></a
        >
      {/if}

      <button
        on:click|preventDefault={() => {}}
        on:svelte-copy={showCopiedLink}
        use:copy={assistantLink}
        ><LinkOutline
          class="inline-block w-6 h-6 text-blue-dark-30 hover:text-blue-dark-50 active:animate-ping"
        /></button
      >

      {#if shareable && assistant.published}
        <button
          on:click|preventDefault={() => {
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
    <a
      href={assistantLink}
      class="flex items-center w-36 gap-2 text-sm text-white font-medium bg-orange rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
      >Start a chat <CirclePlusSolid size="sm" class="inline" /></a
    >
  </div>
</div>
