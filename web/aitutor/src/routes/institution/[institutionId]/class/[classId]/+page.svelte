<script lang="ts">
  import {writable} from "svelte/store";
  import { goto } from "$app/navigation";
  import { enhance } from "$app/forms";
  import ChatInput from "$lib/components/ChatInput.svelte";

  export let data;

  let loading = writable(false);

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
</script>

<div class="v-full h-full flex items-center">
  <div class="m-auto w-9/12">
    {#if isConfigured}
      <form action="?/newThread" method="POST" use:enhance={handleSubmit}>
        <ChatInput loading={$loading} />
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
