<script lang="ts">
  import { page } from '$app/stores';
  import { copy } from 'svelte-copy';
  import { toast } from '@zerodevx/svelte-toast';
  import { Heading } from 'flowbite-svelte';
  import {
    EyeOutline,
    EyeSlashOutline,
    LinkOutline,
    PenSolid,
    CirclePlusSolid
  } from 'flowbite-svelte-icons';
  import type { Assistant } from '$lib/api';

  export let assistant: Assistant;
  export let creator: { email: string };
  export let editable = false;

  // Get the full URL to use the assistant
  $: assistantLink = `${$page.url.protocol}//${$page.url.host}/class/${assistant.class_id}?assistant=${assistant.id}`;

  // Show info that we copied the link to the clipboard
  const showCopiedLink = (e: Event) => {
    e.preventDefault();
    e.stopPropagation();
    toast.push('Copied link to clipboard', {
      duration: 1000
    });
  };
</script>

<div
  class="flex flex-col gap-2 {editable
    ? 'bg-gold-light'
    : 'bg-orange-light'} rounded-2xl px-8 pt-6 py-4 pr-4 pb-8"
>
  <Heading tag="h4" class="flex gap-4 text-3xl font-normal items-center">
    <div>
      {assistant.name}
      {#if !assistant.published}
        <EyeSlashOutline class="inline-block w-5 h-5 mr-1 text-gray-500" />
      {:else}
        <EyeOutline class="inline-block w-5 h-5 mr-1 text-orange" />
      {/if}
    </div>

    <div class="ml-auto flex shrink-0 items-center gap-2">
      {#if editable}
        <a
          class="text-blue-dark-30 hover:text-blue-dark-50"
          href="/class/{assistant.class_id}/assistant/{assistant.id}"><PenSolid size="md" /></a
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
    </div>
  </Heading>
  <div class="text-xs mb-4">Created by <b>{creator.email}</b></div>
  <div class="mb-4 font-light">{assistant.description || '(No description provided)'}</div>
  <div>
    <a
      href={assistantLink}
      class="flex items-center w-36 gap-2 text-sm text-white font-medium bg-orange rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
      >Start a chat <CirclePlusSolid size="sm" class="inline" /></a
    >
  </div>
</div>
