<script lang="ts">
  import {writable} from "svelte/store";
  import { goto } from "$app/navigation";
  import { enhance } from "$app/forms";
  import ChatInput from "$lib/components/ChatInput.svelte";
  import {Helper, GradientButton, Dropdown, DropdownItem, Label} from 'flowbite-svelte';
  import { ChevronDownSolid } from 'flowbite-svelte-icons';

  export let data;

  let loading = writable(false);
  let assistant = writable(data?.assistants[0] || {});
  let aiSelectOpen = false;

  $: isConfigured = data?.hasAssistants && data?.hasBilling;

  // Handle form submission
  const handleSubmit = () => {
    $loading = true;

    return ({result, update}) => {
      if (result.type === "success") {
        goto(`/institution/${data.institutionId}/class/${result.data.thread.class_id}/thread/${result.data.thread.id}`);
      } else {
        $loading = false;
        alert("Chat failed! Please try again.");
      }
    };
  };

  const selectAi = (asst) => {
    $assistant = asst;
    aiSelectOpen = false;
  };
</script>

<div class="v-full h-full flex items-center">
  <div class="m-auto w-9/12">
    {#if isConfigured}
      <div class="text-center my-2 w-full">
        <GradientButton color="tealToLime" on:click={() => aiSelectOpen = true}>{$assistant.name} <ChevronDownSolid class="w-3 h-3 ms-2" /></GradientButton>
          <Dropdown bind:open={aiSelectOpen}>
          {#each data.assistants as asst}
            <DropdownItem on:click={() => selectAi(asst)}>
              {asst.name}
              <Helper class="text-xs">{data.assistantCreators[asst.creator_id].email}</Helper>
            </DropdownItem>
          {/each}
        </Dropdown>
      </div>
      <form action="?/newThread" method="POST" use:enhance={handleSubmit}>
        <ChatInput loading={$loading} />
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
