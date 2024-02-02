<script lang="ts">
  import {writable} from "svelte/store";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { enhance } from "$app/forms";
  import ChatInput from "$lib/components/ChatInput.svelte";
  import {Helper, GradientButton, Dropdown, DropdownItem, Label} from 'flowbite-svelte';
  import { EyeSlashOutline, ChevronDownSolid } from 'flowbite-svelte-icons';
  import * as api from "$lib/api";

  export let data;

  let loading = writable(false);
  let assistant = writable(data?.assistants[0] || {});
  let aiSelectOpen = false;

  $: isConfigured = data?.hasAssistants && data?.hasBilling;
  $: linkedAssistant = parseInt($page.url.searchParams.get('assistant') || '0', 10);
  $: {
    if (linkedAssistant && data?.assistants) {
      const selectedAssistant = (data?.assistants || []).find((asst) => asst.id === linkedAssistant);
      if (selectedAssistant) {
        $assistant = selectedAssistant;
      }
    }
  }

  // Handle file upload
  const handleUpload = (f: File, onProgress: (p: number) => void) => {
    return api.uploadUserFile(data.class.id, data.me.user.id, f, {onProgress});
  }

  // Handle form submission
  const handleSubmit = () => {
    $loading = true;

    return ({result, update}) => {
      if (result.type === "success") {
        goto(`/class/${result.data.thread.class_id}/thread/${result.data.thread.id}`);
      } else {
        $loading = false;
        alert("Chat failed! Please try again.");
      }
    };
  };

  const selectAi = (asst) => {
    goto(`/class/${data.class.id}/?assistant=${asst.id}`);
    aiSelectOpen = false;
  };

  const openDropdown = () => {
    aiSelectOpen = true;
  };
</script>

<div class="v-full h-full flex items-center">
  <div class="m-auto w-10/12">
    {#if isConfigured}
      <div class="text-center my-2 w-full">
        <GradientButton color="tealToLime" on:click={() => openDropdown()} on:touchstart={() => openDropdown()}>{$assistant.name} <ChevronDownSolid class="w-3 h-3 ms-2" /></GradientButton>
          <Dropdown bind:open={aiSelectOpen}>
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
        <ChatInput loading={$loading} upload={handleUpload} />
        <input type="hidden" name="assistant_id" bind:value={$assistant.id} />
        <input type="hidden" name="parties" bind:value={data.me.user.id} />
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
