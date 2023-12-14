<script lang="ts">
  import * as api from '$lib/api';
  import { enhance } from "$app/forms";
  import {browser} from '$app/environment';
  import {invalidateAll} from '$app/navigation';
  import {Avatar} from "flowbite-svelte";
  import SvelteMarkdown from "svelte-markdown";
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput from "$lib/components/ChatInput.svelte";

  export let data;

  let thread = [];

  let lastLoadedRun = "";

  $: {
    thread = (data?.messages?.data || []);
    thread.sort((a, b) => a.created_at - b.created_at);
    if (!lastLoadedRun) {
      lastLoadedRun = data?.run?.id;
    }

    if (browser && data.currentThread && !api.finished(data?.run)) {
      api.getLastThreadRun(fetch, data.class.id, data.currentThread).then((result) => {
        if (result.run.id !== lastLoadedRun) {
          lastLoadedRun = result.run.id;
          invalidateAll();
        }
      });
    }
  }

  const getName = (message) => {
    if (message.role === "user") {
      const participant = data?.participants[message?.metadata?.user_id];
      return participant?.name || participant?.email;
    } else {
      return "AI Tutor"
    }
  }

  const getImage = (message) => {
    if (message.role === "user") {
      return data?.participants[message?.metadata?.user_id]?.image_url;
    }

    return "";
  }
</script>

<div class="container py-8 h-full flex flex-col">
  <div class="w-full px-2 flex-grow overflow-y-auto">
    {#each thread as message}
      <div class="py-4 px-6 flex gap-x-3">
        <div>
          {#if message.role === "user"}
            <Avatar size="sm" src={getImage(message)} />
          {:else}
            <Logo size="8" />
          {/if}
        </div>
        <div>
          <div class="font-bold text-gray-400">{getName(message)}</div>
          {#each message.content as content}
            <div class="leading-7"><SvelteMarkdown source="{content.text.value}" /></div>
          {/each}
        </div>
      </div>
    {/each}
  </div>
  <div class="w-9/12 mx-auto mt-auto shrink-0">
    <form action="?/newMessage" method="POST" use:enhance>
      <ChatInput />
    </form>
  </div>
</div>
