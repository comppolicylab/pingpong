<script lang="ts">
  import { navigating, page } from '$app/stores';
  import { goto, invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { errorMessage } from '$lib/errors';
  import { blur } from 'svelte/transition';
  import {
    Accordion,
    AccordionItem,
    Avatar,
    Button,
    Card,
    Dropdown,
    DropdownItem,
    Modal,
    Span
  } from 'flowbite-svelte';
  import { DoubleBounce } from 'svelte-loading-spinners';
  import Markdown from '$lib/components/Markdown.svelte';
  import Logo from '$lib/components/Logo.svelte';
  import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
  import {
    RefreshOutline,
    CodeOutline,
    ImageSolid,
    CogOutline,
    EyeOutline,
    EyeSlashOutline,
    LockSolid
  } from 'flowbite-svelte-icons';
  import { parseTextContent } from '$lib/content';
  import { ThreadManager } from '$lib/stores/thread';
  import AttachmentDeletedPlaceholder from '$lib/components/AttachmentDeletedPlaceholder.svelte';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import { writable } from 'svelte/store';
  import ModeratorsTable from '$lib/components/ModeratorsTable.svelte';

  export let data;

  $: classId = parseInt($page.params.classId);
  $: threadId = parseInt($page.params.threadId);
  $: threadMgr = new ThreadManager(fetch, classId, threadId, data.threadData);
  $: isPrivate = data.class.private || false;
  $: teachers = data?.supervisors || [];
  $: canDeleteThread = data.canDeleteThread;
  $: canPublishThread = data.canPublishThread;
  $: canViewAssistant = data.canViewAssistant;
  $: messages = threadMgr.messages;
  $: participants = threadMgr.participants;
  $: published = threadMgr.published;
  $: error = threadMgr.error;
  $: threadManagerError = $error?.detail || null;
  $: assistantId = threadMgr.assistantId;
  $: isCurrentUser = $participants.user.includes('Me');
  let trashThreadFiles = writable<string[]>([]);
  $: threadAttachments = threadMgr.attachments;
  $: allFiles = Object.fromEntries(
    Object.entries($threadAttachments)
      .filter(([k, v]) => !$trashThreadFiles.includes(k))
      .map(([k, v]) => [
        k,
        {
          state: 'success',
          progress: 100,
          file: { type: v.content_type, name: v.name },
          response: v,
          promise: Promise.resolve(v)
        } as api.FileUploadInfo
      ])
  );
  $: fileSearchAcceptedFiles = supportsFileSearch
    ? data.uploadInfo.fileTypes({
        file_search: true,
        code_interpreter: false,
        vision: false
      })
    : null;
  $: codeInterpreterAcceptedFiles = supportsCodeInterpreter
    ? data.uploadInfo.fileTypes({
        file_search: false,
        code_interpreter: true,
        vision: false
      })
    : null;
  $: visionAcceptedFiles = supportsVision
    ? data.uploadInfo.fileTypes({
        file_search: false,
        code_interpreter: false,
        vision: true
      })
    : null;
  $: fileSearchAttachmentCount = Object.entries($threadAttachments).filter(
    ([k, v]) =>
      !$trashThreadFiles.includes(k) && (fileSearchAcceptedFiles ?? '').includes(v.content_type)
  ).length;
  $: codeInterpreterAttachmentCount = Object.entries($threadAttachments).filter(
    ([k, v]) =>
      !$trashThreadFiles.includes(k) &&
      (codeInterpreterAcceptedFiles ?? '').includes(v.content_type)
  ).length;

  let supportsVision = false;
  $: {
    const supportVisionModels = (data.models.filter((model) => model.supports_vision) || []).map(
      (model) => model.id
    );
    supportsVision = supportVisionModels.includes(data.threadModel);
  }
  let visionSupportOverride: boolean | undefined;
  $: {
    visionSupportOverride = data.models.find(
      (model) => model.id === data.threadModel
    )?.vision_support_override;
  }
  $: submitting = threadMgr.submitting;
  $: waiting = threadMgr.waiting;
  $: loading = threadMgr.loading;
  $: canFetchMore = threadMgr.canFetchMore;
  $: supportsFileSearch = data.availableTools.includes('file_search') || false;
  $: supportsCodeInterpreter = data.availableTools.includes('code_interpreter') || false;
  // TODO - should figure this out by checking grants instead of participants
  $: canSubmit = !!$participants.user && $participants.user.includes('Me');
  $: assistantDeleted = !$assistantId && $assistantId === 0;
  let useLatex = false;
  $: {
    const assistant = data.assistants.find((assistant) => assistant.id === $assistantId);
    if (assistant) {
      useLatex = assistant.use_latex || false;
    } else {
      console.warn(`Definition for assistant ${$assistantId} not found.`);
    }
  }
  let showModerators = false;

  let currentMessageAttachments: api.ServerFile[] = [];
  // Get the name of the participant in the chat thread.
  const getName = (message: api.OpenAIMessage) => {
    if (message.role === 'user') {
      if (message?.metadata?.is_current_user) {
        return data?.me?.user?.name || data?.me?.user?.email || 'Anonymous User';
      }
      return (message?.metadata?.name as string | undefined) || 'Anonymous User';
    } else {
      // Note that we need to distinguish between unknown and deleted assistants.
      if ($assistantId !== null) {
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
      sadToast(
        `Failed to load code interpreter results. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
      );
    }
  };

  // Handle sending a message
  const postMessage = async ({
    message,
    code_interpreter_file_ids,
    file_search_file_ids,
    vision_file_ids,
    callback
  }: ChatInputMessage) => {
    try {
      await threadMgr.postMessage(
        data.me.user!.id,
        message,
        callback,
        code_interpreter_file_ids,
        file_search_file_ids,
        vision_file_ids,
        currentMessageAttachments
      );
    } catch (e) {
      callback({
        success: false,
        errorMessage: `Failed to send message. Error: ${errorMessage(e, "Something went wrong while sending your message. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.")}`,
        message_sent: false
      });
    }
  };

  // Handle submit on the chat input
  const handleSubmit = async (e: CustomEvent<ChatInputMessage>) => {
    await postMessage(e.detail);
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

  const handleDismissError = () => {
    threadMgr.dismissError();
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
      sadToast(
        `Failed to ${verb} thread. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
      );
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
      sadToast(
        `Failed to delete thread. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
      );
    }
  };

  /*
   * Delete a file from the thread.
   */
  const removeFile = async (evt: CustomEvent<api.FileUploadInfo>) => {
    const file = evt.detail;
    if (file.state === 'deleting' || !(file.response && 'file_id' in file.response)) {
      return;
    } else {
      allFiles[(file.response as api.ServerFile).file_id].state = 'deleting';
      const result = await api.deleteThreadFile(
        fetch,
        data.class.id,
        threadId,
        (file.response as api.ServerFile).file_id
      );
      if (result.$status >= 300) {
        allFiles[(file.response as api.ServerFile).file_id].state = 'success';
        sadToast(`Failed to delete file: ${result.detail || 'unknown error'}`);
      } else {
        trashThreadFiles.update((files) => [...files, (file.response as api.ServerFile).file_id]);
        happyToast('Thread file successfully deleted.');
      }
    }
  };

  const showModeratorsModal = () => {
    showModerators = true;
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
      {@const attachment_file_ids = message.data.attachments
        ? new Set(message.data.attachments.map((attachment) => attachment.file_id))
        : []}
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
            {#if content.type === 'text'}
              <div class="leading-6">
                <Markdown
                  content={parseTextContent(
                    content.text,
                    api.fullPath(`/class/${classId}/thread/${threadId}`)
                  )}
                  syntax={true}
                  latex={useLatex}
                />
              </div>
              {#if attachment_file_ids}
                <div class="flex flex-wrap gap-2">
                  {#each attachment_file_ids as file_id}
                    {#if allFiles[file_id]}
                      <FilePlaceholder
                        info={allFiles[file_id]}
                        mimeType={data.uploadInfo.mimeType}
                        on:delete={removeFile}
                      />
                    {:else}
                      <AttachmentDeletedPlaceholder {file_id} />
                    {/if}
                  {/each}
                </div>
              {/if}
            {:else if content.type === 'code'}
              <div class="leading-6 w-full">
                <Accordion flush>
                  <AccordionItem open>
                    <span slot="header"
                      ><div class="flex-row flex items-center space-x-2">
                        <div><CodeOutline size="lg" /></div>
                        <div>Code Interpreter</div>
                      </div></span
                    >
                    <pre style="white-space: pre-wrap;" class="text-black">{content.code}</pre>
                  </AccordionItem>
                </Accordion>
              </div>
            {:else if content.type === 'code_interpreter_call_placeholder'}
              <Card padding="md" class="max-w-full flex-row flex items-center justify-between">
                <div class="flex-row flex items-center space-x-2">
                  <div><CodeOutline size="lg" /></div>
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
            {:else if content.type === 'code_output_image_file'}
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
            {:else if content.type === 'image_file'}
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
  </div>
  <Modal title="Group Moderators" bind:open={showModerators} autoclose outsideclose
    ><ModeratorsTable moderators={teachers} /></Modal
  >
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
          bind:attachments={currentMessageAttachments}
          {threadManagerError}
          {visionAcceptedFiles}
          {fileSearchAcceptedFiles}
          {codeInterpreterAcceptedFiles}
          {visionSupportOverride}
          {assistantDeleted}
          {canViewAssistant}
          canSubmit={canSubmit && !assistantDeleted && canViewAssistant}
          disabled={!canSubmit || assistantDeleted || !!$navigating || !canViewAssistant}
          loading={$submitting || $waiting}
          {fileSearchAttachmentCount}
          {codeInterpreterAttachmentCount}
          upload={handleUpload}
          remove={handleRemove}
          on:submit={handleSubmit}
          on:dismissError={handleDismissError}
        />
        <div class="flex gap-2 items-center w-full text-sm justify-between grow my-3">
          <div class="flex gap-2 grow shrink min-w-0">
            {#if !$published && isPrivate}
              <LockSolid size="sm" class="text-orange" />
              <Span class="text-gray-600 text-xs font-normal"
                ><Button
                  class="p-0 text-gray-600 text-xs underline font-normal"
                  on:click={showModeratorsModal}
                  on:touchstart={showModeratorsModal}>Moderators</Button
                > <span class="font-semibold">cannot</span> see this thread or your name. {#if isCurrentUser}For
                  more information, please review <a
                    href="/privacy-policy"
                    rel="noopener noreferrer"
                    class="underline">PingPong's privacy statement</a
                  >.
                {/if}Assistants can make mistakes. Check important info.</Span
              >
            {:else if !$published}
              <EyeSlashOutline size="sm" class="text-orange" />
              <Span class="text-gray-600 text-xs font-normal"
                ><Button
                  class="p-0 text-gray-600 text-xs underline font-normal"
                  on:click={showModeratorsModal}
                  on:touchstart={showModeratorsModal}>Moderators</Button
                > can see this thread but not {isCurrentUser ? 'your' : "the user's"} name.
                {#if isCurrentUser}For more information, please review <a
                    href="/privacy-policy"
                    rel="noopener noreferrer"
                    class="underline">PingPong's privacy statement</a
                  >.
                {/if}Assistants can make mistakes. Check important info.</Span
              >
            {:else}
              <EyeOutline size="sm" class="text-orange" />
              <Span class="text-gray-600 text-xs font-normal"
                >Everyone in this group can see this thread but not {isCurrentUser
                  ? 'your'
                  : "the user's"} name. Assistants can make mistakes. Check important info.</Span
              >
            {/if}
          </div>

          <div class="shrink-0 grow-0 h-auto">
            <CogOutline class="dark:text-white cursor-pointer w-6 h-4 font-light" size="lg" />
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
