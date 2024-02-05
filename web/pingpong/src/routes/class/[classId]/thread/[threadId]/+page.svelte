<script lang="ts">
  import type { SubmitFunction } from '@sveltejs/kit';
  import { writable } from 'svelte/store';
  import * as api from '$lib/api';
  import { sadToast } from '$lib/toast';
  import { blur } from 'svelte/transition';
  import { enhance } from '$app/forms';
  import { Span, Avatar } from 'flowbite-svelte';
  import { Pulse, SyncLoader } from 'svelte-loading-spinners';
  import Markdown from '$lib/components/Markdown.svelte';
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput from '$lib/components/ChatInput.svelte';
  import { EyeSlashOutline } from 'flowbite-svelte-icons';

  export let data;

  let submitting = writable(false);
  let messages: api.OpenAIMessage[] = [];
  let participants: api.ThreadParticipants = { user: {}, assistant: {} };
  let priv = false;
  let classId = 0;
  let waiting = writable(false);
  $: thread = data?.thread?.store;
  $: threadStatus = $thread?.$status || 0;
  $: threadUsers = ($thread as api.ThreadWithMeta)?.thread?.users || [];
  $: {
    if ($thread && Object.hasOwn($thread, 'messages')) {
      const t = $thread as api.ThreadWithMeta;
      messages = t.messages.sort((a, b) => a.created_at - b.created_at);
      participants = t.participants;
      priv = t.thread.private;
      classId = t.thread.class_id;
      if (!loading) {
        waiting.set(!api.finished(t.run));
      }
    } else {
      messages = [];
      participants = { user: {}, assistant: {} };
      priv = false;
      classId = 0;
    }
  }
  $: loading = !$thread && data?.thread?.loading;
  $: canSubmit =
    !!participants.user && data?.me?.user?.id && !!participants.user[data?.me?.user?.id];

  // Get the name of the participant in the chat thread.
  const getName = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      const userId = message?.metadata?.user_id as number | undefined;
      if (!userId) {
        return 'Unknown';
      }
      const participant = participants.user[userId];
      return participant?.email || 'Unknown';
    } else {
      return (
        participants.assistant[($thread as api.ThreadWithMeta).thread.assistant_id] ||
        'PingPong Bot'
      );
    }
  };

  // Get the avatar URL of the participant in the chat thread.
  const getImage = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      const userId = message?.metadata?.user_id as number | undefined;
      if (!userId) {
        return '';
      }
      return participants.user[userId]?.image_url;
    }
    // TODO - custom image for the assistant

    return '';
  };

  // Scroll to the bottom of the chat thread.
  const scroll = (el: HTMLDivElement, messageList: api.OpenAIMessage[]) => {
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
    };
  };

  // Handle sending a message
  const handleSubmit: SubmitFunction = () => {
    if ($waiting) {
      sadToast(
        'A response to the previous message is being generated. Please wait before sending a new message.'
      );
      return;
    }
    $submitting = true;

    return async ({ result, update }) => {
      if (result.type !== 'success') {
        sadToast('Chat failed! Please try again.');
        return;
      }

      $waiting = true;

      await data.thread.refresh(false);
      update();

      $submitting = false;

      // Do a blocking refresh if the completion is still running
      if (!api.finished(($thread as api.ThreadWithMeta).run)) {
        await data.thread.refresh(true);
      }

      $waiting = false;
    };
  };

  // Handle file upload
  const handleUpload = (f: File, onProgress: (p: number) => void) => {
    return api.uploadUserFile(data.class.id, data.me.user!.id, f, { onProgress });
  };

  // Handle file removal
  const handleRemove = async (fileId: number) => {
    const result = await api.deleteUserFile(fetch, data.class.id, data.me.user!.id, fileId);
    if (result.$status >= 300) {
      sadToast(`Failed to delete file. Error: ${result.detail || 'unknown error'}`);
      throw new Error(result.detail || 'unknown error');
    }
  };
</script>

<div class="relative py-8 h-full w-full">
  {#if threadStatus >= 400}
    <div class="absolute top-0 left-0 flex h-full w-full items-center">
      <div class="m-auto">
        <div class="text-center">
          <div class="text-2xl font-bold text-gray-600">Error loading thread.</div>
          <div class="text-gray-400">{$thread?.detail || 'An unknown error occurred.'}</div>
        </div>
      </div>
    </div>
  {/if}
  {#if loading}
    <div class="absolute top-0 left-0 flex h-full w-full items-center">
      <div class="m-auto" transition:blur={{ amount: 10 }}>
        <Pulse color="#d97706" />
      </div>
    </div>
  {/if}
  <div class="w-full h-full flex flex-col justify-between">
    <div class="overflow-y-auto pb-4 px-12" use:scroll={messages}>
      {#each messages as message}
        <div class="py-4 px-6 flex gap-x-3">
          <div>
            {#if message.role === 'user'}
              <Avatar size="sm" src={getImage(message)} />
            {:else}
              <Logo size={8} />
            {/if}
          </div>
          <div class="max-w-full">
            <div class="font-bold text-gray-400">{getName(message)}</div>
            {#each message.content as content}
              {#if content.type == 'text'}
                <div class="leading-7"><Markdown content={content.text.value} /></div>
              {:else if content.type == 'image_file'}
                <div class="leading-7">
                  <img
                    src="/api/v1/class/{classId}/image/{content.image_file.file_id}"
                    alt="File icon"
                  />
                </div>
              {:else}
                <div class="leading-7"><pre>{JSON.stringify(content, null, 2)}</pre></div>
              {/if}
            {/each}
          </div>
        </div>
      {/each}
      {#if $waiting}
        <div class="w-full flex justify-center" transition:blur={{ amount: 10 }}>
          <SyncLoader color="#d97706" size="40" />
        </div>
      {/if}
    </div>

    {#if !loading}
      <div class="w-full bottom-8 bg-gradient-to-t from-white to-transparent">
        <form
          class="w-11/12 mx-auto"
          action="?/newMessage"
          method="POST"
          use:enhance={handleSubmit}
        >
          <ChatInput
            mimeType={data.uploadInfo.mimeType}
            maxSize={data.uploadInfo.private_file_max_size}
            accept={data.uploadInfo.acceptString}
            disabled={!canSubmit}
            loading={$submitting || $waiting}
            upload={handleUpload}
            remove={handleRemove}
          />
        </form>
      </div>
    {/if}
  </div>

  {#if priv}
    <div
      class="absolute top-0 left-0 flex gap-2 px-4 py-2 items-center w-full bg-amber-200 text-sm"
    >
      <EyeSlashOutline size="sm" class="text-gray-400" />
      <Span class="text-gray-400">This thread is private to</Span>
      <Span class="text-gray-600">{threadUsers.map((u) => u.email).join(', ')}</Span>
    </div>
  {/if}
</div>

<style lang="css">
  :global(.katex) {
    font-size: 1.2em;
  }
  :global(.katex-html) {
    display: none;
  }
</style>
