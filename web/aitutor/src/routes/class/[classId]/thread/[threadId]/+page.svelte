<script lang="ts">
  import {error} from "@sveltejs/kit";
  import {writable} from "svelte/store";
  import * as api from '$lib/api';
  import { blur } from 'svelte/transition';
  import { enhance } from "$app/forms";
  import {browser} from '$app/environment';
  import {invalidateAll} from '$app/navigation';
  import {Span, Avatar } from "flowbite-svelte";
  import { Pulse, SyncLoader } from 'svelte-loading-spinners';
  import SvelteMarkdown from "svelte-markdown";
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput from "$lib/components/ChatInput.svelte";
  import CodeRenderer from "$lib/components/CodeRenderer.svelte";
  import CodeSpanRenderer from "$lib/components/CodeSpanRenderer.svelte";
  import {
    EyeSlashOutline,
  } from 'flowbite-svelte-icons';

  export let data;

  let submitting = writable(false);
  $: thread = data?.thread?.store;
  $: messages = ($thread?.messages || []).sort((a, b) => a.created_at - b.created_at);
  $: participants = $thread?.participants || {};
  $: loading = !$thread && data?.thread?.loading;
  $: priv = !!$thread?.thread?.private;

  $: classId = $thread?.thread?.class_id;

  let waiting = writable(false);
  $: {
    if (!loading && $thread && $thread.run) {
      waiting.set(!api.finished($thread.run));
    }
  }

  // Get the name of the participant in the chat thread.
  const getName = (message) => {
    if (message.role === "user") {
      const participant = participants.user[message?.metadata?.user_id];
      return participant?.name || participant?.email;
    } else {
      return participants.assistant[$thread.thread.assistant_id] || "AI Tutor";
    }
  }

  // Get the avatar URL of the participant in the chat thread.
  const getImage = (message) => {
    if (message.role === "user") {
      return participants[message?.metadata?.user_id]?.image_url;
    }
    // TODO - image for the assistant

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
    if ($waiting) {
      alert("A response to the previous message is being generated. Please wait before sending a new message.");
      return;
    }
    $submitting = true;
    return async ({result, update}) => {
      if (result.type !== "success") {
        alert("Chat failed! Please try again.");
        return;
      }

      $waiting = true;

      await data.thread.refresh(false);
      update();

      $submitting = false;

      // Do a blocking refresh if the completion is still running
      if (!api.finished($thread.run)) {
        await data.thread.refresh(true);
      }

      $waiting = false;
    };
  };

  // Supply a custom renderer for certain tags.
  const customRenderers = {
    code: CodeRenderer,
    codespan: CodeSpanRenderer,
  };
</script>

<div class="relative py-8 h-full w-full">
  {#if $thread?.$status >= 400}
    <div class="absolute top-0 left-0 flex h-full w-full items-center">
      <div class="m-auto">
        <div class="text-center">
          <div class="text-2xl font-bold text-gray-600">Error loading thread.</div>
          <div class="text-gray-400">{$thread?.detail || "An unknown error occurred."}</div>
        </div>
      </div>
    </div>
  {/if}
  {#if loading}
    <div class="absolute top-0 left-0 flex h-full w-full items-center">
      <div class="m-auto" transition:blur={{amount: 10}}>
        <Pulse color="#d97706" />
      </div>
    </div>
  {/if}
  <div class="w-full h-full flex flex-col justify-between">
  <div class="overflow-y-auto pb-4 px-12" use:scroll={messages}>
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
            {#if content.type == "text"}
              <div class="leading-7"><SvelteMarkdown source="{content.text.value}" /></div>
            {:else if content.type == "image_file"}
              <div class="leading-7"><img src="/api/v1/class/{classId}/image/{content.image_file.file_id}" /></div>
            {:else}
              <div class="leading-7"><pre>{JSON.stringify(content, null, 2)}</pre></div>
            {/if}
          {/each}
        </div>
      </div>
    {/each}
  {#if $waiting}
    <div class="w-full flex justify-center" transition:blur={{amount: 10}}><SyncLoader color="#d97706" size="40" /></div>

   {/if}
  </div>

  {#if !loading}
  <div class="w-full bottom-8 bg-gradient-to-t from-white to-transparent">
    <form class="w-11/12 mx-auto" action="?/newMessage" method="POST" use:enhance={handleSubmit}>
      <ChatInput loading={$submitting || $waiting} />
    </form>
  </div>
  {/if}
  </div>

  {#if priv}
  <div class="absolute top-0 left-0 flex gap-2 px-4 py-2 items-center w-full bg-amber-200 text-sm">
    <EyeSlashOutline size="sm" class="text-gray-400" />
    <Span class="text-gray-400">This thread is private to</Span>
    <Span class="text-gray-600">{($thread?.thread?.users || []).map(u => u.email).join(", ")}</Span>
  </div>
  {/if}
</div>
