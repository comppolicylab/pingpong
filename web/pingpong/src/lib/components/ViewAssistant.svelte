<script lang="ts">
  import { page } from '$app/stores';
  import { copy } from 'svelte-copy';
  import { toast } from '@zerodevx/svelte-toast';
  import { Heading } from 'flowbite-svelte';
  import { EyeOutline, EyeSlashOutline, LinkOutline } from 'flowbite-svelte-icons';
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

<div class="flex flex-col gap-2">
  <Heading tag="h4" class="pb-3 flex justify-between">
    <div>
      {#if !assistant.published}
        <EyeSlashOutline class="inline-block w-6 h-6 mr-2 text-gray-300" />
      {:else}
        <EyeOutline class="inline-block w-6 h-6 mr-2 text-amber-600" />
      {/if}
      {assistant.name}
    </div>

    {#if editable}
      <a href="/class/{assistant.class_id}/assistant/{assistant.id}">Edit</a>
    {/if}

    <button
      on:click|preventDefault={() => {}}
      on:svelte-copy={showCopiedLink}
      use:copy={assistantLink}
      ><LinkOutline
        class="inline-block w-6 h-6 text-gray-700 hover:text-green-700 active:animate-ping"
      /></button
    >
  </Heading>
  <div>Created by {creator.email}</div>
  <div>{assistant.description || '(No description provided)'}</div>
  <div>
    <a href={assistantLink}>Start a chat</a>
  </div>
</div>
