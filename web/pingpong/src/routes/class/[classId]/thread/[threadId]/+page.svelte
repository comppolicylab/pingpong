<script lang="ts">
  import { page } from '$app/stores';
  import * as api from '$lib/api';
  import { sadToast } from '$lib/toast';
  import { errorMessage } from '$lib/errors';
  import { blur } from 'svelte/transition';
  import { Span, Avatar } from 'flowbite-svelte';
  import { Pulse, DoubleBounce } from 'svelte-loading-spinners';
  import Markdown from '$lib/components/Markdown.svelte';
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import { EyeSlashOutline } from 'flowbite-svelte-icons';
  import { parseTextContent } from '$lib/content';
  import { ThreadManager } from '$lib/stores/thread';

  export let data;

  let fileTypes = '';
  $: classId = parseInt($page.params.classId);
  $: threadId = parseInt($page.params.threadId);
  $: threadMgr = new ThreadManager(fetch, classId, threadId, data.threadData);
  $: messages = threadMgr.messages;
  $: participants = threadMgr.participants;
  $: published = threadMgr.published;
  $: error = threadMgr.error;
  $: assistantId = threadMgr.assistantId;
  $: users = threadMgr.users;
  $: submitting = threadMgr.submitting;
  $: waiting = threadMgr.waiting;
  $: loading = threadMgr.loading;
  $: {
    // Figure out the capabilities of assistants in the thread
    const assts = data.assistants.filter((a) => Object.hasOwn($participants.assistant, a.id));
    fileTypes = data.uploadInfo.fileTypesForAssistants(...assts);
  }
  // TODO - should figure this out by checking grants instead of participants
  $: canSubmit =
    !!$participants.user && data?.me?.user?.id && !!$participants.user[data?.me?.user?.id];

  // Get the name of the participant in the chat thread.
  const getName = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      const userId = message?.metadata?.user_id as number | undefined;
      if (!userId) {
        return 'Unknown';
      }
      const participant = $participants.user[userId];
      return participant?.email || 'Unknown';
    } else {
      if ($assistantId) {
        return $participants.assistant[$assistantId] || 'PingPong Bot';
      }
      return 'PingPong Bot';
    }
  };

  // Get the avatar URL of the participant in the chat thread.
  const getImage = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      const userId = message?.metadata?.user_id as number | undefined;
      if (!userId) {
        return '';
      }
      return $participants.user[userId]?.image_url;
    }
    // TODO - custom image for the assistant

    return '';
  };

  // Scroll to the bottom of the chat thread.
  const scroll = (el: HTMLDivElement, messageList: unknown[]) => {
    // Scroll to the bottom of the element.
    el.scrollTo({
      top: el.scrollHeight,
      behavior: 'smooth'
    });
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
  const postMessage = async ({ message, file_ids }: ChatInputMessage) => {
    try {
      await threadMgr.postMessage(data.me.user!.id, message, file_ids);
    } catch (e) {
      sadToast(`Failed to send message. Error: ${errorMessage(e)}`);
    }
  };

  // Handle submit on the chat input
  const handleSubmit = async (e: CustomEvent<ChatInputMessage>) => {
    await postMessage(e.detail);
    e.detail.callback?.();
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
  {#if $loading}
    <div class="absolute top-0 left-0 flex h-full w-full items-center">
      <div class="m-auto" transition:blur={{ amount: 10 }}>
        <Pulse color="#0ea5e9" />
      </div>
    </div>
  {/if}
  <div class="w-full h-full flex flex-col justify-between">
    <div class="overflow-y-auto pb-4 px-12" use:scroll={$messages}>
      {#each $messages as message}
        <div class="py-4 px-6 flex gap-x-3">
          <div class="shrink-0">
            {#if message.data.role === 'user'}
              <Avatar size="sm" src={getImage(message.data)} />
            {:else}
              <Logo size={8} />
            {/if}
          </div>
          <div class="max-w-full">
            <div class="font-bold text-gray-400 mb-1">{getName(message.data)}</div>
            {#each message.data.content as content}
              {#if content.type == 'text'}
                <div class="leading-7">
                  <Markdown
                    content={parseTextContent(
                      content.text,
                      api.fullPath(`/class/${classId}/thread/${threadId}`)
                    )}
                  />
                </div>
              {:else if content.type == 'image_file'}
                <div class="leading-7 w-full">
                  <img
                    class="img-attachment m-auto"
                    src={api.fullPath(
                      `/class/${classId}/thread/${threadId}/image/${content.image_file.file_id}`
                    )}
                    alt="Attachment generated by the assistant"
                  />
                </div>
              {:else}
                <div class="leading-7"><pre>{JSON.stringify(content, null, 2)}</pre></div>
              {/if}
            {/each}
          </div>
        </div>
      {/each}

      {#if $error}
        <div class="flex w-full items-center">
          <div class="m-auto">
            <div class="text-center">
              <div class="text-2xl font-bold text-red-600">Error loading thread.</div>
              <div class="text-red-400">{errorMessage($error)}</div>
            </div>
          </div>
        </div>
      {/if}
    </div>

    {#if !$loading}
      <div class="w-full bottom-8 bg-gradient-to-t from-white to-transparent">
        <div class="w-11/12 mx-auto relative">
          {#if $waiting || $submitting}
            <div
              class="w-full flex justify-center absolute -top-10"
              transition:blur={{ amount: 10 }}
            >
              <DoubleBounce color="#0ea5e9" size="30" />
            </div>
          {/if}
          <ChatInput
            mimeType={data.uploadInfo.mimeType}
            maxSize={data.uploadInfo.private_file_max_size}
            accept={fileTypes}
            disabled={!canSubmit}
            loading={$submitting || $waiting}
            upload={handleUpload}
            remove={handleRemove}
            on:submit={handleSubmit}
          />
        </div>
      </div>
    {/if}
  </div>

  {#if !$published}
    <div
      class="absolute top-0 left-0 flex gap-2 px-4 py-2 items-center w-full bg-amber-200 text-sm"
    >
      <EyeSlashOutline size="sm" class="text-gray-400" />
      <Span class="text-gray-400">This thread is private to</Span>
      <Span class="text-gray-600">{$users.map((u) => u.email).join(', ')}</Span>
    </div>
  {/if}
</div>

<style lang="css">
  .img-attachment {
    max-width: min(95%, 700px);
  }
</style>
