<script lang="ts" context="module">
  export type ChatInputMessage = {
    code_interpreter_file_ids: string[];
    file_search_file_ids: string[];
    vision_file_ids: string[];
    message: string;
    callback: (success: boolean, errorMessage: string | null, message_sent: boolean) => void;
  };
</script>

<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { writable } from 'svelte/store';
  import type { Writable } from 'svelte/store';
  import { Button, Popover, Span, Dropdown, DropdownItem } from 'flowbite-svelte';
  import { page } from '$app/stores';
  import type {
    MimeTypeLookupFn,
    FileRemover,
    FileUploader,
    FileUploadInfo,
    ServerFile
  } from '$lib/api';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import FileUpload from '$lib/components/FileUpload.svelte';
  import { sadToast } from '$lib/toast';
  import type { FileUploadPurpose } from '$lib/api';
  import {
    ArrowUpOutline,
    CloseOutline,
    ExclamationCircleOutline,
    EyeSlashOutline,
    LockSolid,
    EyeOutline,
    CogOutline
  } from 'flowbite-svelte-icons';

  const dispatcher = createEventDispatcher();

  /**
   * Whether to allow sending.
   */
  export let disabled = false;
  /**
   * Whether the user can reply in this thread.
   */
  export let canSubmit = false;
  /**
   * Whether the assistant associated with this thread has been deleted.
   */
  export let assistantDeleted = false;
  /**
   * Whether the user has permissions to interact with this assistant.
   */
  export let canViewAssistant = true;
  /**
   * Whether we're waiting for an in-flight request.
   */
  export let loading = false;
  /**
   * Error message provided by thread manager.
   */
  export let threadManagerError: string | null = null;
  /**
   * The maximum height of the container before scrolling.
   */
  export let maxHeight = 200;
  /**
   * Function to call for uploading files, if uploading is allowed.
   */
  export let upload: FileUploader | null = null;
  /**
   * Function to call for deleting files.
   */
  export let remove: FileRemover | null = null;

  /**
   * Files to accept for file search. If null, file search is disabled.
   */
  export let fileSearchAcceptedFiles: string | null = null;
  export let fileSearchAttachmentCount = 0;
  /**
   * Files to accept for code interpreter. If null, code interpreter is disabled.
   */
  export let codeInterpreterAcceptedFiles: string | null = null;
  export let codeInterpreterAttachmentCount = 0;
  /**
   * Files to accept for Vision. If null, vision capabilities are disabled.
   */
  export let visionAcceptedFiles: string | null = null;
  /**
   * Max upload size.
   */
  export let maxSize: number = 0;

  /**
   * The list of files being uploaded.
   */
  export let attachments: ServerFile[] = [];

  /**
   * Mime type lookup function.
   */
  export let mimeType: MimeTypeLookupFn;

  export let isPrivate = false;
  export let isNewChat = true;
  export let isCurrentUser = false;
  export let isPublished = false;
  export let canPublishThread = false;
  export let canDeleteThread = false;

  // Input container
  let containerRef: HTMLDivElement;
  // Text area reference for fixing height.
  let ref: HTMLTextAreaElement;
  // Real (visible) text area input reference.
  let realRef: HTMLTextAreaElement;
  // Container for the list of files, for calculating height.
  let allFileListRef: HTMLDivElement;

  // The list of files being uploaded.
  let allFiles = writable<FileUploadInfo[]>([]);
  $: uploading = $allFiles.some((f) => f.state === 'pending');
  let purpose: FileUploadPurpose | null = null;
  $: purpose =
    (codeInterpreterAcceptedFiles || fileSearchAcceptedFiles) && visionAcceptedFiles
      ? 'multimodal'
      : codeInterpreterAcceptedFiles || fileSearchAcceptedFiles
        ? 'assistants'
        : visionAcceptedFiles
          ? 'vision'
          : null;
  $: codeInterpreterFiles = $allFiles
    .filter((f) => f.state === 'success' && (f.response as ServerFile).code_interpreter_file_id)
    .map((f) => (f.response as ServerFile).file_id);
  $: codeInterpreterFileIds = codeInterpreterFiles.join(',');

  $: fileSearchFiles = $allFiles
    .filter((f) => f.state === 'success' && (f.response as ServerFile).file_search_file_id)
    .map((f) => (f.response as ServerFile).file_id);
  $: fileSearchFileIds = fileSearchFiles.join(',');

  let threadCodeInterpreterMaxCount = 20;
  let threadFileSearchMaxCount = 10_000;

  $: visionFileIds = $allFiles
    .filter((f) => f.state === 'success' && (f.response as ServerFile).vision_file_id)
    .map((f) => (f.response as ServerFile).vision_file_id)
    .join(',');

  $: attachments = $allFiles
    .filter(
      (f) =>
        f.state === 'success' &&
        ((f.response as ServerFile).code_interpreter_file_id ||
          (f.response as ServerFile).file_search_file_id)
    )
    .map((f) => f.response as ServerFile);

  $: currentFileSearchFileCount = fileSearchAttachmentCount + fileSearchFiles.length;
  $: currentCodeInterpreterFileCount = codeInterpreterAttachmentCount + codeInterpreterFiles.length;

  $: currentAccept =
    (attachments.length >= 10 || currentCodeInterpreterFileCount >= threadCodeInterpreterMaxCount
      ? ''
      : (codeInterpreterAcceptedFiles ?? '')) +
    (attachments.length >= 10 || currentFileSearchFileCount >= threadFileSearchMaxCount
      ? ''
      : (fileSearchAcceptedFiles ?? '')) +
    (visionFileIds.length >= 10 ? '' : (visionAcceptedFiles ?? ''));

  $: tooManyFiles =
    (attachments.length >= 10 ||
      currentFileSearchFileCount >= threadFileSearchMaxCount ||
      currentCodeInterpreterFileCount >= threadCodeInterpreterMaxCount) &&
    visionFileIds.length >= 10;

  // Fix the height of the textarea to match the content.
  // The technique is to render an off-screen textarea with a scrollheight,
  // then set the height of the visible textarea to match. Other techniques
  // temporarily set the height to auto, but this causes the screen to flicker
  // and the other flow elements to jump around.
  const fixHeight = (el: HTMLTextAreaElement) => {
    if (!ref) {
      return;
    }
    ref.style.visibility = 'hidden';
    ref.style.paddingRight = el.style.paddingRight;
    ref.style.paddingLeft = el.style.paddingLeft;
    ref.style.width = `${el.clientWidth}px`;
    ref.value = el.value;
    const scrollHeight = ref.scrollHeight;
    el.style.height = `${scrollHeight + 8}px`;
    if (scrollHeight > 80) {
      containerRef.classList.toggle('rounded-[16px]', true);
      containerRef.classList.toggle('rounded-full', false);
    } else {
      containerRef.classList.toggle('rounded-[16px]', false);
      containerRef.classList.toggle('rounded-full', true);
    }
  };

  // Focus textarea when component is mounted. Since we can only use `use` on
  // native DOM elements, we need to wrap the textarea in a div and then
  // access its child to imperatively focus it.
  const init = (node: HTMLDivElement, newThreadId: string) => {
    document.getElementById('message')?.focus();
    return {
      update: () => {
        document.getElementById('message')?.focus();
      }
    };
  };

  let errorMessage: string | null = null;
  $: combinedErrorMessage = errorMessage || threadManagerError;

  const dismissError = () => {
    errorMessage = null;
    dispatcher('dismissError');
  };

  // Submit the form.
  const submit = () => {
    const code_interpreter_file_ids = codeInterpreterFileIds
      ? codeInterpreterFileIds.split(',')
      : [];
    const file_search_file_ids = fileSearchFileIds ? fileSearchFileIds.split(',') : [];
    const vision_file_ids = visionFileIds ? visionFileIds.split(',') : [];

    if (!ref.value || disabled) {
      return;
    }
    errorMessage = null;
    const message = ref.value;
    const realMessage = realRef.value;
    const tempFiles = $allFiles;
    $allFiles = [];
    document.getElementById('message')?.focus();
    ref.value = '';
    realRef.value = '';
    fixHeight(realRef);

    dispatcher('submit', {
      file_search_file_ids,
      code_interpreter_file_ids,
      vision_file_ids,
      message,
      callback: (
        success: boolean,
        _errorMessage: string | null = null,
        message_sent: boolean = true
      ) => {
        if (success) {
          return;
        }
        if (!message_sent) {
          errorMessage =
            _errorMessage ||
            'We faced an error while trying to send your message. Please try again.';
          $allFiles = tempFiles;
          ref.value = message;
          realRef.value = realMessage;
          fixHeight(realRef);
        }
        errorMessage =
          _errorMessage ||
          'We faced an error while generating a response to your message. Your message was successfully sent. Please try again by sending a new message.';
        isPrivate = true;
      }
    });
  };

  // Submit form when Enter (but not Shift+Enter) is pressed in textarea
  const maybeSubmit = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!disabled) {
        submit();
      }
    }
  };

  // Fix the height of the container when the file list changes.
  const fixFileListHeight = (node: HTMLDivElement, newFiles: FileUploadInfo[]) => {
    const update = () => {
      const el = document.getElementById('message');
      if (!el) {
        return;
      }
      fixHeight(el as HTMLTextAreaElement);
    };
    return { update };
  };

  // Handle updates from the file upload component.
  const handleFilesChange = (e: CustomEvent<Writable<FileUploadInfo[]>>) => {
    allFiles = e.detail;
  };

  // Remove a file from the list / the server.
  const removeFile = (evt: CustomEvent<FileUploadInfo>) => {
    if (!remove) {
      return;
    }
    const file = evt.detail;
    if (file.state === 'pending' || file.state === 'deleting') {
      return;
    } else if (file.state === 'error') {
      allFiles.update((f) => f.filter((x) => x !== file));
    } else {
      allFiles.update((f) => {
        const idx = f.indexOf(file);
        if (idx >= 0) {
          f[idx].state = 'deleting';
        }
        return f;
      });
      let removePromises: Promise<void>[] = [remove((file.response as ServerFile).id)];
      if ((file.response as ServerFile).vision_obj_id) {
        const visionFileId = Number((file.response as ServerFile).vision_obj_id);
        if (!isNaN(visionFileId)) {
          removePromises.push(remove(visionFileId));
        }
      }
      Promise.all(removePromises)
        .then(() => {
          allFiles.update((f) => f.filter((x) => x !== file));
        })
        .catch(() => {
          /* no-op */
        });
    }
  };

  const handleTextAreaInput = (e: Event) => {
    const target = e.target as HTMLTextAreaElement;
    fixHeight(target);
  };
</script>

<div use:init={$page.params.threadId} class="w-full relative">
  <input type="hidden" name="vision_file_ids" bind:value={visionFileIds} />
  <input type="hidden" name="file_search_file_ids" bind:value={fileSearchFileIds} />
  <input type="hidden" name="code_interpreter_file_ids" bind:value={codeInterpreterFileIds} />
  <div class="flex px-1 md:px-2 flex-col">
    <div style="opacity: 1; height: auto;">
      {#if $allFiles.length > 0}
        <div
          class="border border-blue-light-40 relative flex -mb-3 gap-2 flex-wrap rounded-t-2xl pb-5 pt-2.5 bg-blue-light-50"
          use:fixFileListHeight={$allFiles}
          bind:this={allFileListRef}
        >
          <div class="flex gap-2 flex-wrap px-2 py-0">
            {#each $allFiles as file}
              <FilePlaceholder {mimeType} info={file} purpose="multimodal" on:delete={removeFile} />
            {/each}
          </div>
        </div>
      {/if}

      {#if combinedErrorMessage}
        <div
          class="border relative z-10 px-3.5 text-chat-error-text border-chat-error-border bg-chat-error-bg -mb-1 rounded-t-xl border-b-0 pb-2.5 pt-2"
        >
          <div class="w-full">
            <div class="flex w-full flex-col items-center md:flex-row gap-2">
              <div class="text-danger-000 flex flex-row items-center gap-2 md:w-full">
                <ExclamationCircleOutline />
                <div>
                  <div class="text-sm">
                    {combinedErrorMessage}
                  </div>
                </div>
              </div>
              <Button
                class="text-chat-error-text -mt-px hover:bg-chat-error-button-hover p-1 rounded-lg"
                on:click={dismissError}
              >
                <CloseOutline class="cursor-pointer" />
              </Button>
            </div>
          </div>
        </div>
      {/if}
    </div>
  </div>
  <div
    class="flex flex-col bg-chat-bg gap-2 border border-chat-border pl-4 pt-2.5 pr-2.5 pb-2.5 items-stretch transition-all duration-200 relative shadow-[0_0.25rem_1.25rem_rgba(254,184,175,0.15)] focus-within:shadow-[0_0.25rem_1.25rem_rgba(253,148,134,0.25)] hover:border-chat-border-hover focus-within:border-chat-border-hover z-20 rounded-t-2xl border-b-0"
  >
    <div class="flex flex-row gap-4" bind:this={containerRef}>
      <textarea
        bind:this={realRef}
        id="message"
        rows="1"
        name="message"
        class="w-full !outline-none focus:ring-0 resize-none border-none bg-transparent p-0 mt-1"
        placeholder={canSubmit
          ? 'Ask me anything'
          : assistantDeleted
            ? 'Read-only thread: the assistant associated with this thread is deleted.'
            : canViewAssistant
              ? 'Read-only thread: You no longer have permissions to interact with this assistant.'
              : "You can't reply in this thread."}
        class:text-gray-700={disabled}
        class:animate-pulse={loading}
        disabled={loading || disabled || !canSubmit || assistantDeleted || !canViewAssistant}
        on:keydown={maybeSubmit}
        on:input={handleTextAreaInput}
        style={`height: 48px; max-height: ${maxHeight}px; font-size: 1rem; line-height: 1.5rem;`}
      />
      <textarea
        bind:this={ref}
        style="position: absolute; visibility: hidden; height: 0px; left: -1000px; top: -1000px"
      />
      <div class="flex flex-row gap-1">
        {#if upload && purpose}
          <FileUpload
            {maxSize}
            accept={currentAccept}
            disabled={loading || disabled || !upload || tooManyFiles || uploading}
            type="multimodal"
            {fileSearchAcceptedFiles}
            {codeInterpreterAcceptedFiles}
            {visionAcceptedFiles}
            documentMaxCount={10}
            visionMaxCount={10}
            currentDocumentCount={attachments.filter(
              (f) => f.file_search_file_id || f.code_interpreter_file_id
            ).length}
            currentVisionCount={visionFileIds.length}
            fileSearchAttachmentCount={currentFileSearchFileCount}
            codeInterpreterAttachmentCount={currentCodeInterpreterFileCount}
            {threadFileSearchMaxCount}
            {threadCodeInterpreterMaxCount}
            {purpose}
            {upload}
            on:error={(e) => sadToast(e.detail.message)}
            on:change={handleFilesChange}
          />
          {#if (codeInterpreterAcceptedFiles || fileSearchAcceptedFiles || visionAcceptedFiles) && !(attachments.length >= 10 || visionFileIds.length >= 10) && !(loading || disabled || !upload) && currentFileSearchFileCount < threadFileSearchMaxCount && currentCodeInterpreterFileCount < threadCodeInterpreterMaxCount}
            <Popover defaultClass="py-2 px-3 w-52 text-sm" arrow={false}
              >Upload files to thread<br />File Search: {currentFileSearchFileCount}/10,000<br
              />Code Interpreter: {currentCodeInterpreterFileCount}/20</Popover
            >
          {:else if currentFileSearchFileCount >= threadFileSearchMaxCount || currentCodeInterpreterFileCount >= threadCodeInterpreterMaxCount}
            <Popover defaultClass="py-2 px-3 w-52 text-sm" arrow={false}
              >Maximum number of thread document attachments reached{visionFileIds.length < 10
                ? '. You can still upload images.'
                : ''}</Popover
            >
          {:else if attachments.length >= 10}
            <Popover defaultClass="py-2 px-3 w-52 text-sm" arrow={false}
              >Maximum number of document attachments reached{visionFileIds.length < 10
                ? '. You can still upload images.'
                : ''}</Popover
            >
          {:else if visionFileIds.length >= 10}
            <Popover defaultClass="py-2 px-3 w-52 text-sm" arrow={false}
              >Maximum number of image uploads reached. You can still upload documents.</Popover
            >
          {:else}
            <Popover arrow={false}>File upload is disabled</Popover>
          {/if}
        {/if}
        <div>
          <Button
            on:click={submit}
            on:touchstart={submit}
            on:keydown={maybeSubmit}
            class={`${loading ? 'animate-pulse cursor-progress' : ''} bg-orange w-8 h-8 p-1 hover:bg-orange-dark `}
            disabled={uploading || loading || disabled}
          >
            <ArrowUpOutline class="w-6 h-6" />
          </Button>
        </div>
      </div>
    </div>
    {#if isNewChat}
      {#if isPrivate}
        <div class="flex gap-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
          <LockSolid size="sm" class="text-orange pt-0" />
          <Span class="text-gray-600 text-xs font-normal"
            >Moderators <span class="font-semibold">cannot</span> see this thread or your name. For
            more information, please review
            <a href="/privacy-policy" rel="noopener noreferrer" class="underline"
              >PingPong's privacy statement</a
            >. Assistants can make mistakes. Check important info.</Span
          >
        </div>
      {:else}
        <div class="flex gap-2 items-start w-full text-sm flex-wrap lg:flex-nowrap">
          <EyeSlashOutline size="sm" class="text-orange pt-0" />
          <Span class="text-gray-600 text-xs font-normal"
            >Moderators can see this thread but not your name. For more information, please review <a
              href="/privacy-policy"
              rel="noopener noreferrer"
              class="underline">PingPong's privacy statement</a
            >. Assistants can make mistakes. Check important info.</Span
          >
        </div>
      {/if}
    {:else}
      <div class="flex gap-2 items-center w-full text-sm justify-between grow">
        <div class="flex gap-2 grow shrink min-w-0">
          {#if !isPublished && isPrivate}
            <LockSolid size="sm" class="text-orange" />
            <Span class="text-gray-600 text-xs font-normal"
              >Moderators <span class="font-semibold">cannot</span> see this thread or your name. {#if isCurrentUser}For
                more information, please review <a
                  href="/privacy-policy"
                  rel="noopener noreferrer"
                  class="underline">PingPong's privacy statement</a
                >.
              {/if}Assistants can make mistakes. Check important info.</Span
            >
          {:else if !isPublished}
            <EyeSlashOutline size="sm" class="text-orange" />
            <Span class="text-gray-600 text-xs font-normal"
              >Moderators can see this thread but not {isCurrentUser ? 'your' : "the user's"} name.
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
            <DropdownItem
              on:click={() => {
                dispatcher('togglePublish');
              }}
              disabled={!canPublishThread}
            >
              <span class:text-gray-300={!canPublishThread}>
                {#if isPublished}
                  Unpublish
                {:else}
                  Publish
                {/if}
              </span>
            </DropdownItem>
            <DropdownItem
              on:click={() => {
                dispatcher('deleteThread');
              }}
              disabled={!canDeleteThread}
            >
              <span class:text-gray-300={!canDeleteThread}>Delete</span>
            </DropdownItem>
          </Dropdown>
        </div>
      </div>
    {/if}
  </div>
</div>
