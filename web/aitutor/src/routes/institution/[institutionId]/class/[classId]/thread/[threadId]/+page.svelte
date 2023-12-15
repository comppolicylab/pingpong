<script lang="ts">
  import {writable} from "svelte/store";
  import * as api from '$lib/api';
  import { blur } from 'svelte/transition';
  import { enhance } from "$app/forms";
  import {browser} from '$app/environment';
  import {invalidateAll} from '$app/navigation';
  import {Avatar, Spinner} from "flowbite-svelte";
  import SvelteMarkdown from "svelte-markdown";
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput from "$lib/components/ChatInput.svelte";

  export let data;

  let submitting = writable(false);
  let waiting = writable(false);
  $: thread = data?.thread?.store;
  $: messages = ($thread?.messages?.data || []).sort((a, b) => a.created_at - b.created_at);
  $: participants = $thread?.participants || {};
  $: loading = !$thread && data?.thread?.loading;

  // Get the name of the participant in the chat thread.
  const getName = (message) => {
    if (message.role === "user") {
      const participant = participants[message?.metadata?.user_id];
      return participant?.name || participant?.email;
    } else {
      return "AI Tutor"
    }
  }

  // Get the avatar URL of the participant in the chat thread.
  const getImage = (message) => {
    if (message.role === "user") {
      return participants[message?.metadata?.user_id]?.image_url;
    }

    return "";
  }

  // Scroll to the bottom of the chat thread.
  const scroll = (el) => {
    // Scroll to the bottom of the element.
    return {
      // TODO - would be good to figure out how to do this without a timeout.
      update: () => {
        setTimeout(() => {
          el.scrollTo({
            top: el.scrollHeight,
            behavior: 'smooth'
          });
        }, 250);
      }
    }
  }

  const handleSubmit = () => {
    $submitting = true;
    return ({result, update}) => {
      $submitting = false;
      $waiting = !api.finished(result.data.run);

      data.thread.refresh().then(() => {
        $waiting = false;
      });

      if (result.type === "success") {
        update();
      } else {
        alert("Chat failed! Please try again.");
      }
    };
  };
</script>

<div class="relative py-8 h-full w-full">
  {#if loading}
    <div class="absolute top-0 left-0 flex h-full w-full items-center">
      <div class="m-auto" transition:blur={{amount: 10}}>
        <Spinner color="blue" />
      </div>
    </div>
  {/if}
  <div class="w-full h-full overflow-y-auto pb-12 px-12" use:scroll={messages}>
    {#each messages as message}
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
  {#if $waiting}
    <div class="text-center w-full" transition:blur={{amount: 10}}><Spinner color="blue" /></div>
   {/if}
  </div>
  <div class="absolute w-full bottom-8 bg-gradient-to-t from-white to-transparent">
    <form class="w-9/12 mx-auto" action="?/newMessage" method="POST" use:enhance={handleSubmit}>
      <ChatInput loading={$submitting} />
    </form>
  </div>
</div>
