<script lang="ts">
  import { navigating, page } from '$app/stores';
  import { goto, invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { errorMessage } from '$lib/errors';
  import { blur } from 'svelte/transition';
  import {
    Span,
    Accordion,
    AccordionItem,
    Avatar,
    Button,
    Dropdown,
    DropdownItem,
    Card
  } from 'flowbite-svelte';
  import { DoubleBounce } from 'svelte-loading-spinners';
  import Markdown from '$lib/components/Markdown.svelte';
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import {
    EyeSlashOutline,
    EyeOutline,
    RefreshOutline,
    DotsHorizontalOutline,
    CodeSolid,
    ImageSolid,
    LockSolid
  } from 'flowbite-svelte-icons';
  import { parseTextContent } from '$lib/content';
  import { ThreadManager } from '$lib/stores/thread';

  export let data;

  $: classId = parseInt($page.params.classId);
  $: threadId = parseInt($page.params.threadId);
  $: threadMgr = new ThreadManager(fetch, classId, threadId, data.threadData);
  $: isPrivate = data.class.private || false;
  $: canDeleteThread = data.canDeleteThread;
  $: canPublishThread = data.canPublishThread;
  $: messages = threadMgr.messages;
  $: participants = threadMgr.participants;
  $: published = threadMgr.published;
  $: error = threadMgr.error;
  $: assistantId = threadMgr.assistantId;
  let externalUserString: string = '';
  $: {
    const filtered = $participants.user
      .filter((user_name) => user_name != 'Me')
      .map((user_name) => user_name || 'Anonymous User');
    if (filtered.length > 0) {
      if (filtered.length === 1) {
        externalUserString = ' and ' + filtered[0];
      } else {
        externalUserString = ', ' + filtered.slice(0, -1).join(', ') + ' and ' + filtered.slice(-1);
      }
    }
  }
  let supportsVision = false;
  $: {
    const supportVisionModels = (data.models.filter((model) => model.supports_vision) || []).map(
      (model) => model.id
    );
    supportsVision = supportVisionModels.includes(data.threadModel);
  }
  $: submitting = threadMgr.submitting;
  $: waiting = threadMgr.waiting;
  $: loading = threadMgr.loading;
  $: canFetchMore = threadMgr.canFetchMore;
  $: supportsFileSearch = data.availableTools.includes('file_search') || false;
  $: supportsCodeInterpreter = data.availableTools.includes('code_interpreter') || false;
  // TODO - should figure this out by checking grants instead of participants
  $: canSubmit = !!$participants.user && $participants.user.includes('Me');

  // Get the name of the participant in the chat thread.
  const getName = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      if (message?.metadata?.is_current_user) {
        return data?.me?.user?.name || data?.me?.user?.email || 'Anonymous User';
      }
      return (message?.metadata?.hashed_name as string | undefined) || 'Anonymous User';
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
      if (message?.metadata?.is_current_user) {
        return data?.me?.profile?.image_url || '';
      }
      return '';
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
          // Don't auto-scroll if the user is not near the bottom of the chat.
          // TODO - we can show an indicator if there are new messages that we'd want to scroll to.
          if (el.scrollTop + el.clientHeight < el.scrollHeight - 600) {
            return;
          }

          el.scrollTo({
            top: el.scrollHeight,
            behavior: 'smooth'
          });
        }, 250);
      }
    };
  };

  // Fetch an earlier page of messages
  const fetchMoreMessages = async () => {
    await threadMgr.fetchMore();
  };

  // Fetch a singular code interpreter step result
  const fetchCodeInterpreterResult = async (content: api.Content) => {
    if (content.type !== 'code_interpreter_call_placeholder') {
      sadToast('Invalid code interpreter request.');
      return;
    }
    try {
      await threadMgr.fetchCodeInterpreterResult(
        content.thread_id,
        content.run_id,
        content.step_id
      );
    } catch (e) {
      sadToast(`Failed to load code interpreter results. Error: ${errorMessage(e)}`);
    }
  };

  // Handle sending a message
  const postMessage = async ({
    message,
    code_interpreter_file_ids,
    file_search_file_ids,
    vision_file_ids
  }: ChatInputMessage) => {
    try {
      await threadMgr.postMessage(
        data.me.user!.id,
        message,
        code_interpreter_file_ids,
        file_search_file_ids,
        vision_file_ids
      );
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
  const handleUpload = (
    f: File,
    onProgress: (p: number) => void,
    purpose: api.FileUploadPurpose = 'assistants'
  ) => {
    return api.uploadUserFile(data.class.id, data.me.user!.id, f, { onProgress }, purpose);
  };

  // Handle file removal
  const handleRemove = async (fileId: number) => {
    const result = await api.deleteUserFile(fetch, data.class.id, data.me.user!.id, fileId);
    if (result.$status >= 300) {
      sadToast(`Failed to delete file. Error: ${result.detail || 'unknown error'}`);
      throw new Error(result.detail || 'unknown error');
    }
  };

  /**
   * Publish or unpublish a thread.
   */
  const togglePublish = async () => {
    if (!threadMgr.thread) {
      return;
    }
    let verb = 'publish';
    try {
      if (threadMgr.thread.private) {
        await threadMgr.publish();
      } else {
        verb = 'unpublish';
        await threadMgr.unpublish();
      }
      invalidateAll();
    } catch (e) {
      sadToast(`Failed to ${verb} thread. Error: ${errorMessage(e)}`);
    }
  };

  /**
   * Delete the thread.
   */
  const deleteThread = async () => {
    if (!threadMgr.thread) {
      return;
    }
    try {
      if (!confirm('Are you sure you want to delete this thread? This cannot be undone!')) {
        return;
      }
      await threadMgr.delete();
      happyToast('Thread deleted.');
      await goto(`/group/${classId}`, { invalidateAll: true });
    } catch (e) {
      sadToast(`Failed to delete thread. Error: ${errorMessage(e)}`);
    }
  };
</script>

<div class="w-full flex flex-col justify-between grow min-h-0 relative">
  <div class="overflow-y-auto pb-4 px-2 lg:px-4" use:scroll={$messages}>
    {#if $canFetchMore}
      <div class="flex justify-center grow">
        <Button size="sm" class="text-sky-600 hover:text-sky-800" on:click={fetchMoreMessages}>
          <RefreshOutline class="w-3 h-3 me-2" /> Load earlier messages ...
        </Button>
      </div>
    {/if}
    {#each $messages as message}
      <div class="py-4 px-6 flex gap-x-3">
        <div class="shrink-0">
          {#if message.data.role === 'user'}
            <Avatar size="sm" src={getImage(message.data)} />
          {:else}
            <Logo size={8} />
          {/if}
        </div>
        <div class="max-w-full w-full">
          <div class="font-semibold text-blue-dark-40 mb-2 mt-1">{getName(message.data)}</div>
          {#each message.data.content as content}
            {#if content.type == 'text'}
              <div class="leading-6">
                <Markdown
                  content={parseTextContent(
                    content.text,
                    api.fullPath(`/class/${classId}/thread/${threadId}`)
                  )}
                />
              </div>
            {:else if content.type == 'code'}
              <div class="leading-6 w-full">
                <Accordion flush>
                  <AccordionItem open>
                    <span slot="header"
                      ><div class="flex-row flex items-center space-x-2">
                        <div><CodeSolid size="lg" /></div>
                        <div>Code Interpreter</div>
                      </div></span
                    >
                    <pre style="white-space: pre-wrap;" class="text-black">{content.code}</pre>
                  </AccordionItem>
                </Accordion>
              </div>
            {:else if content.type == 'code_interpreter_call_placeholder'}
              <Card padding="md" class="max-w-full flex-row flex items-center justify-between">
                <div class="flex-row flex items-center space-x-2">
                  <div><CodeSolid size="lg" /></div>
                  <div>Code Interpreter</div>
                </div>

                <div class="flex flex-wrap items-center gap-2">
                  <Button
                    outline
                    disabled={$loading || $submitting || $waiting}
                    pill
                    size="xs"
                    color="alternative"
                    on:click={() => fetchCodeInterpreterResult(content)}
                    on:touchstart={() => fetchCodeInterpreterResult(content)}
                  >
                    Load Code Interpreter Results
                  </Button>
                </div></Card
              >
            {:else if content.type == 'code_output_image_file'}
              <Accordion flush>
                <AccordionItem>
                  <span slot="header"
                    ><div class="flex-row flex items-center space-x-2">
                      <div><ImageSolid size="lg" /></div>
                      <div>Code Interpreter Output</div>
                    </div></span
                  >
                  <div class="leading-6 w-full">
                    <img
                      class="img-attachment m-auto"
                      src={api.fullPath(
                        `/class/${classId}/thread/${threadId}/image/${content.image_file.file_id}`
                      )}
                      alt="Attachment generated by the assistant"
                    />
                  </div>
                </AccordionItem>
              </Accordion>
            {:else if content.type == 'image_file'}
              <div class="leading-6 w-full">
                <img
                  class="img-attachment m-auto"
                  src={api.fullPath(
                    `/class/${classId}/thread/${threadId}/image/${content.image_file.file_id}`
                  )}
                  alt="Attachment generated by the assistant"
                />
              </div>
            {:else}
              <div class="leading-6"><pre>{JSON.stringify(content, null, 2)}</pre></div>
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
    <div class="w-full bg-gradient-to-t from-white to-transparent">
      <div class="w-11/12 mx-auto relative flex flex-col">
        {#if $waiting || $submitting}
          <div class="w-full flex justify-center absolute -top-10" transition:blur={{ amount: 10 }}>
            <DoubleBounce color="#0ea5e9" size="30" />
          </div>
        {/if}
        <ChatInput
          mimeType={data.uploadInfo.mimeType}
          maxSize={data.uploadInfo.private_file_max_size}
          visionAcceptedFiles={supportsVision
            ? data.uploadInfo.fileTypes({
                file_search: false,
                code_interpreter: false,
                vision: true
              })
            : null}
          fileSearchAcceptedFiles={supportsFileSearch
            ? data.uploadInfo.fileTypes({
                file_search: true,
                code_interpreter: false,
                vision: false
              })
            : null}
          codeInterpreterAcceptedFiles={supportsCodeInterpreter
            ? data.uploadInfo.fileTypes({
                file_search: false,
                code_interpreter: true,
                vision: false
              })
            : null}
          disabled={!canSubmit || !!$navigating}
          loading={$submitting || $waiting}
          upload={handleUpload}
          remove={handleRemove}
          on:submit={handleSubmit}
        />
        <div
          class="flex gap-2 px-4 py-2 items-center w-full text-sm flex-nowrap justify-between grow"
        >
          <div class="flex gap-1 grow shrink min-w-0 flex-wrap">
            {#if !$published && isPrivate}
              <div
                class="flex gap-2 px-4 py-2 items-center w-full text-sm flex-wrap lg:flex-nowrap"
              >
                <LockSolid size="sm" class="text-orange" />
                <Span class="text-gray-400 text-xs">This thread is only visible to you.</Span>
              </div>
            {:else if !$published}
              <EyeSlashOutline size="sm" class="text-orange" />
              <Span class="text-gray-400 text-xs whitespace-nowrap"
                >This thread is visible to the moderation team{externalUserString
                  ? `, yourself${externalUserString}`
                  : ' and yourself'}.</Span
              >
            {:else}
              <EyeOutline size="sm" class="text-orange" />
              <Span class="text-gray-400 text-xs"
                >This thread is visible to everyone in this group.</Span
              >
            {/if}
          </div>

          <div class="shrink-0 grow-0 h-auto">
            <DotsHorizontalOutline
              class="dots-menu dark:text-white cursor-pointer bg-white dark:bg-slate-700"
              size="lg"
            />
            <Dropdown>
              <DropdownItem on:click={togglePublish} disabled={!canPublishThread}>
                <span class:text-gray-300={!canPublishThread}>
                  {#if $published}
                    Unpublish
                  {:else}
                    Publish
                  {/if}
                </span>
              </DropdownItem>
              <DropdownItem on:click={deleteThread} disabled={!canDeleteThread}>
                <span class:text-gray-300={!canDeleteThread}>Delete</span>
              </DropdownItem>
            </Dropdown>
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>

<style lang="css">
  .img-attachment {
    max-width: min(95%, 700px);
  }
</style>
