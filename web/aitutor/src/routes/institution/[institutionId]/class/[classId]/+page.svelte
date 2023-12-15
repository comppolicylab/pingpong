<script lang="ts">
  import {writable} from "svelte/store";
  import { goto } from "$app/navigation";
  import { enhance } from "$app/forms";
  import ChatInput from "$lib/components/ChatInput.svelte";

  export let data;

  let loading = writable(false);

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
    {#if data.isConfigured}
      <form action="?/newThread" method="POST" use:enhance={handleSubmit}>
        <ChatInput loading={$loading} />
      </form>
    {:else}
      <div class="text-center">
        <h1 class="text-2xl font-bold">No assistant configured</h1>
      </div>
    {/if}
  </div>
</div>
