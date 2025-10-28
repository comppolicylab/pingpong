<script lang="ts" context="module">
  export type CallbackParams = {
    success: boolean;
    errorMessage: string | null;
    message_sent: boolean;
  };

  export type ChatInputMessage = {
    code_interpreter_file_ids: string[];
    file_search_file_ids: string[];
    vision_file_ids: string[];
    visionFileImageDescriptions: ImageProxy[];
    message: string;
    callback: ({ success, errorMessage, message_sent }: CallbackParams) => void;
  };
</script>

<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { writable } from 'svelte/store';
  import type { Writable } from 'svelte/store';
  import { Button, Heading, Li, List, Modal, P, Popover } from 'flowbite-svelte';
  import { page } from '$app/stores';
  import { browser } from '$app/environment';
  import type {
    MimeTypeLookupFn,
    FileRemover,
    FileUploader,
    FileUploadInfo,
    ServerFile,
    ImageProxy
  } from '$lib/api';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import FileUpload from '$lib/components/FileUpload.svelte';
  import { sadToast } from '$lib/toast';
  import type { FileUploadPurpose } from '$lib/api';
  import {
    ArrowUpOutline,
    BanOutline,
    CloseOutline,
    ExclamationCircleOutline,
    FileImageOutline,
    InfoCircleOutline,
    QuestionCircleOutline
  } from 'flowbite-svelte-icons';
  import Sanitize from '$lib/components/Sanitize.svelte';
  import DropdownBadge from './DropdownBadge.svelte';

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

  export let assistantVersion: number | null = null;
  export let threadVersion: number | null = null;

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
   * (Based on model capabilities)
   * Files to accept for Vision. If null, vision capabilities are disabled.
   */
  export let visionAcceptedFiles: string | null = null;
  /**
   * Whether the specific AI Provider supports Vision for this model.
   */
  export let visionSupportOverride: boolean | undefined = undefined;
  export let useImageDescriptions = false;
  /**
   * (Based on model capabilities AND AI Provider capabilities)
   * Files to accept for Vision. If null, vision capabilities are disabled.
   */
  let finalVisionAcceptedFiles: string | null = null;
  $: finalVisionAcceptedFiles =
    visionSupportOverride === false && !useImageDescriptions ? null : visionAcceptedFiles;
  let visionOverrideModalOpen = false;
  let visionUseImageDescriptionsModalOpen = false;
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
    codeInterpreterAcceptedFiles && fileSearchAcceptedFiles && finalVisionAcceptedFiles
      ? 'fs_ci_multimodal'
      : codeInterpreterAcceptedFiles && finalVisionAcceptedFiles
        ? 'ci_multimodal'
        : fileSearchAcceptedFiles && finalVisionAcceptedFiles
          ? 'fs_multimodal'
          : codeInterpreterAcceptedFiles || fileSearchAcceptedFiles
            ? 'assistants'
            : finalVisionAcceptedFiles
              ? 'vision'
              : null;
  $: codeInterpreterFiles = (codeInterpreterAcceptedFiles ? $allFiles : [])
    .filter((f) => f.state === 'success' && (f.response as ServerFile).code_interpreter_file_id)
    .map((f) => (f.response as ServerFile).file_id);
  $: codeInterpreterFileIds = codeInterpreterFiles.join(',');

  $: fileSearchFiles = (fileSearchAcceptedFiles ? $allFiles : [])
    .filter((f) => f.state === 'success' && (f.response as ServerFile).file_search_file_id)
    .map((f) => (f.response as ServerFile).file_id);
  $: fileSearchFileIds = fileSearchFiles.join(',');

  let threadCodeInterpreterMaxCount = 20;
  let threadFileSearchMaxCount = 20;

  $: visionFiles = (finalVisionAcceptedFiles ? $allFiles : [])
    .filter((f) => f.state === 'success' && (f.response as ServerFile).vision_file_id)
    .map((f) => (f.response as ServerFile).vision_file_id);

  $: visionFileIds = visionFiles.join(',');
  let visionFileImageDescriptions: ImageProxy[] = [];
  $: visionFileImageDescriptions = (finalVisionAcceptedFiles ? $allFiles : [])
    .filter((f) => f.state === 'success' && (f.response as ServerFile).image_description)
    .map((f) => ({
      name: (f.response as ServerFile).name,
      description: (f.response as ServerFile).image_description ?? 'No description',
      content_type: (f.response as ServerFile).content_type,
      complements: (f.response as ServerFile).file_id
    }));

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
  $: tooManyFileSearchFiles = currentFileSearchFileCount >= threadFileSearchMaxCount;
  $: tooManyCodeInterpreterFiles = currentCodeInterpreterFileCount >= threadCodeInterpreterMaxCount;
  $: tooManyAttachments = attachments.length >= 10;
  $: tooManyVisionFiles = visionFiles.length >= 10;

  // When one of the file upload types is disabled, we need to exclude it from the list of accepted files from the other types, otherwise we will still try to upload it.
  $: fileSearchStringToExclude = !tooManyFileSearchFiles ? '' : (fileSearchAcceptedFiles ?? '');
  $: codeInterpreterStringToExclude = !tooManyCodeInterpreterFiles
    ? ''
    : (codeInterpreterAcceptedFiles ?? '');
  $: visionStringToExclude = !tooManyVisionFiles ? '' : (finalVisionAcceptedFiles ?? '');
  $: currentFileSearchAcceptedFiles = Array.from(
    new Set(
      (tooManyFileSearchFiles ? '' : (fileSearchAcceptedFiles ?? ''))
        .split(',')
        .filter(
          (file) =>
            !codeInterpreterStringToExclude.split(',').includes(file) &&
            !visionStringToExclude.split(',').includes(file)
        )
    )
  ).join(',');
  $: currentCodeInterpreterAcceptedFiles = Array.from(
    new Set(
      (tooManyCodeInterpreterFiles ? '' : (codeInterpreterAcceptedFiles ?? ''))
        .split(',')
        .filter(
          (file) =>
            !fileSearchStringToExclude.split(',').includes(file) &&
            !visionStringToExclude.split(',').includes(file)
        )
    )
  ).join(',');
  $: currentVisionAcceptedFiles = Array.from(
    new Set(
      (tooManyVisionFiles ? '' : (finalVisionAcceptedFiles ?? ''))
        .split(',')
        .filter(
          (file) =>
            !fileSearchStringToExclude.split(',').includes(file) &&
            !codeInterpreterStringToExclude.split(',').includes(file)
        )
    )
  ).join(',');
  $: currentAccept =
    currentFileSearchAcceptedFiles +
    ',' +
    currentCodeInterpreterAcceptedFiles +
    ',' +
    currentVisionAcceptedFiles;

  $: tooManyFiles =
    (tooManyAttachments || tooManyFileSearchFiles || tooManyCodeInterpreterFiles) &&
    tooManyVisionFiles;

  const focusMessage = () => {
    if (!browser) {
      return;
    }
    document.getElementById('message')?.focus();
  };

  $: if (!loading || !uploading) {
    focusMessage();
  }

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
    focusMessage();
    return {
      update: () => {
        focusMessage();
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
    const code_interpreter_file_ids = (codeInterpreterAcceptedFiles ? codeInterpreterFileIds : '')
      ? codeInterpreterFileIds.split(',')
      : [];
    const file_search_file_ids = (fileSearchAcceptedFiles ? fileSearchFileIds : '')
      ? fileSearchFileIds.split(',')
      : [];
    const vision_file_ids = (finalVisionAcceptedFiles ? visionFileIds : '')
      ? visionFileIds.split(',')
      : [];

    if (!ref.value || disabled) {
      return;
    }
    errorMessage = null;
    const message = ref.value;
    const realMessage = realRef.value;
    const tempFiles = $allFiles;
    $allFiles = [];
    focusMessage();
    ref.value = '';
    realRef.value = '';
    fixHeight(realRef);

    dispatcher('submit', {
      file_search_file_ids,
      code_interpreter_file_ids,
      vision_file_ids,
      visionFileImageDescriptions,
      message,
      callback: (params: CallbackParams) => {
        if (params.success) {
          return;
        }
        if (!params.message_sent) {
          errorMessage =
            params.errorMessage ||
            'We faced an error while trying to send your message. Please try again.';
          $allFiles = tempFiles;
          ref.value = message;
          realRef.value = realMessage;
          fixHeight(realRef);
        }
        errorMessage =
          params.errorMessage ||
          'We faced an error while generating a response to your message. Your message was successfully sent. Please try again by sending a new message.';
      }
    });
  };

  // Submit form when Enter (but not Shift+Enter) is pressed in textarea
  const maybeSubmit = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && canSubmit && !assistantDeleted && canViewAssistant && !loading) {
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
    } else if (
      file.state === 'success' &&
      (file.response as ServerFile).image_description &&
      (file.response as ServerFile).id === 0 &&
      (file.response as ServerFile).file_id === ''
    ) {
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
          allFiles.update((f) => {
            const idx = f.indexOf(file);
            if (idx >= 0) {
              f[idx].state = 'success';
            }
            return f;
          });
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
      {#if canSubmit && assistantVersion !== null && threadVersion !== null && assistantVersion > threadVersion}
        <div
          class="border border-gray-300 -mb-4 relative flex gap-2 flex-wrap rounded-t-2xl border-b-0 pt-2.5 pb-6 px-3.5 bg-gray-50"
          use:fixFileListHeight={$allFiles}
          bind:this={allFileListRef}
        >
          <div class="w-full">
            <div class="flex w-full flex-col items-center md:flex-row gap-2">
              <div class="text-gray-600 flex flex-row items-center gap-4 md:w-full">
                <div class="flex flex-row items-start gap-2">
                  <InfoCircleOutline />
                  <div>
                    <div class="text-sm">
                      You are using an older version of this assistant, which relies on an OpenAI
                      service that may be slower or less reliable. To get the best experience, start
                      a new chat.
                    </div>
                  </div>
                </div>
                <Button
                  class="border border-gray-800 from-gray-800 bg-gradient-to-t to-gray-600  text-white hover:bg-gradient-to-t hover:from-gray-700 hover:to-gray-500 hover:border-gray-700 shrink-0 py-1.5 px-3 text-xs md:text-sm"
                  on:click={() => dispatcher('startNewChat')}
                >
                  Start a new chat
                </Button>
              </div>
            </div>
          </div>
        </div>
      {/if}
      {#if $allFiles.length > 0}
        <div
          class="border border-blue-light-40 relative flex -mb-3 gap-2 flex-wrap rounded-t-2xl z-10 pb-5 pt-2.5 bg-blue-light-50"
          use:fixFileListHeight={$allFiles}
          bind:this={allFileListRef}
        >
          <div class="flex gap-2 flex-wrap px-2 py-0">
            {#each $allFiles as file}
              <FilePlaceholder
                {mimeType}
                info={file}
                purpose="fs_ci_multimodal"
                on:delete={removeFile}
              />
            {/each}
          </div>
        </div>
      {/if}

      {#if combinedErrorMessage}
        <div
          class="border relative z-20 px-3.5 text-brown-dark border-red-light-30 bg-red-light-40 -mb-1 rounded-t-xl border-b-0 pb-2.5 pt-2"
        >
          <div class="w-full">
            <div class="flex w-full flex-col items-center md:flex-row gap-2">
              <div class="text-danger-000 flex flex-row items-center gap-2 md:w-full">
                <ExclamationCircleOutline />
                <div>
                  <div class="text-sm">
                    <Sanitize html={combinedErrorMessage} />
                  </div>
                </div>
              </div>
              <Button
                class="text-brown-dark -mt-px hover:bg-red-light-50 p-1 rounded-lg"
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
    class="flex flex-col bg-seasalt gap-2 border border-melon pl-4 py-2.5 pr-3 items-stretch transition-all duration-200 relative shadow-[0_0.25rem_1.25rem_rgba(254,184,175,0.15)] focus-within:shadow-[0_0.25rem_1.25rem_rgba(253,148,134,0.25)] hover:border-coral-pink focus-within:border-coral-pink z-20 rounded-2xl"
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
              ? "You can't reply in this thread."
              : 'Read-only thread: You no longer have permissions to interact with this assistant.'}
        class:text-gray-700={disabled}
        disabled={!canSubmit || assistantDeleted || !canViewAssistant}
        on:keydown={maybeSubmit}
        on:input={handleTextAreaInput}
        style={`max-height: ${maxHeight}px; font-size: 1rem; line-height: 1.5rem;`}
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
            {useImageDescriptions}
            visionAcceptedFiles={finalVisionAcceptedFiles}
            documentMaxCount={10}
            visionMaxCount={10}
            currentDocumentCount={attachments.filter(
              (f) => f.file_search_file_id || f.code_interpreter_file_id
            ).length}
            currentVisionCount={visionFiles.length}
            fileSearchAttachmentCount={currentFileSearchFileCount}
            codeInterpreterAttachmentCount={currentCodeInterpreterFileCount}
            {threadFileSearchMaxCount}
            {threadCodeInterpreterMaxCount}
            {purpose}
            {upload}
            on:error={(e) => sadToast(e.detail.message)}
            on:change={handleFilesChange}
          />
          {#if (codeInterpreterAcceptedFiles || fileSearchAcceptedFiles || finalVisionAcceptedFiles) && !(tooManyAttachments || tooManyVisionFiles) && !(loading || disabled || !upload) && !tooManyFileSearchFiles && !tooManyCodeInterpreterFiles}
            <Popover defaultClass="w-52" arrow={false}
              ><div class="flex flex-col h-fit align-center">
                {#if visionSupportOverride === false && !useImageDescriptions}
                  <Button
                    on:click={() => (visionOverrideModalOpen = true)}
                    class="flex flex-row justify-between items-center bg-amber-700 rounded-t-md rounded-b-none py-2 px-3"
                    ><span class="uppercase text-xs font-medium text-white leading-none"
                      >No Vision capabilities</span
                    >
                    <QuestionCircleOutline color="white" /></Button
                  >{:else if visionSupportOverride === false && useImageDescriptions}
                  <Button
                    on:click={() => (visionUseImageDescriptionsModalOpen = true)}
                    class="flex flex-row justify-between items-center bg-sky-700 rounded-t-md rounded-b-none py-2 px-3"
                    ><span class="uppercase text-xs font-medium text-white leading-none text-start"
                      >Experimental<br />Vision Support</span
                    >
                    <QuestionCircleOutline color="white" /></Button
                  >{/if}<span class="pt-2 px-3 text-sm"
                  >{finalVisionAcceptedFiles &&
                  (fileSearchAcceptedFiles || codeInterpreterAcceptedFiles)
                    ? 'Add photos and files'
                    : 'Add files'}</span
                >{#if fileSearchAcceptedFiles || codeInterpreterAcceptedFiles}<span
                    class="px-3 text-sm"
                    >Documents: {Math.max(
                      currentFileSearchFileCount,
                      currentCodeInterpreterFileCount
                    )}/20</span
                  >{/if}
                {#if finalVisionAcceptedFiles}
                  <span class="pb-2 px-3 text-sm">Photos: {visionFiles.length}/10</span>
                {/if}
              </div></Popover
            >
          {:else if tooManyFileSearchFiles || tooManyCodeInterpreterFiles}
            <Popover defaultClass="py-2 px-3 w-52 text-sm" arrow={false}
              >You can't add any more files in this conversation{visionFiles.length < 10
                ? `. You can still upload photos${codeInterpreterAcceptedFiles && tooManyCodeInterpreterFiles ? ' (.webp only)' : ''}.`
                : '.'}</Popover
            >
          {:else if tooManyAttachments}
            <Popover defaultClass="py-2 px-3 w-52 text-sm" arrow={false}
              ><div class="flex flex-col h-fit align-center">
                <span class="pb-2 text-sm"
                  >You can't upload any more files {tooManyVisionFiles ? 'or photos' : ''} with this
                  message{!tooManyVisionFiles
                    ? '. You can add more photos to this message.'
                    : '.'}</span
                >{#if !tooManyVisionFiles}<span class="text-sm"
                    >Photos: {visionFiles.length}/10</span
                  >{/if}
              </div></Popover
            >
          {:else if tooManyVisionFiles}
            <Popover defaultClass="py-2 px-3 w-52 text-sm" arrow={false}
              >Maximum number of image uploads reached.{fileSearchAcceptedFiles ||
              codeInterpreterAcceptedFiles
                ? ' You can still upload documents.'
                : ''}</Popover
            >
          {:else}
            <Popover defaultClass="py-2 px-3 w-52 text-sm" arrow={false}
              >File upload is disabled</Popover
            >
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
  </div>
</div>

<Modal
  classHeader="text-gray-700"
  class="text-gray-700"
  bind:open={visionOverrideModalOpen}
  autoclose
  outsideclose
>
  <div class="flex flex-col gap-5 p-4">
    <div class="flex flex-col items-center gap-0">
      <div class="flex items-center justify-center relative h-40">
        <BanOutline class="text-amber-600 w-40 h-40 z-10 absolute" strokeWidth="1.5" />
        <FileImageOutline class="text-stone-400 opacity-75 w-24 h-24" strokeWidth="1" />
      </div>
      <Heading tag="h2" class="text-xl font-semibold text-center"
        >Vision capabilities are currently unavailable</Heading
      >
    </div>
    <div class="flex flex-col gap-1">
      <div class="text-md text-wrap">
        Your group's AI Provider does not support Vision capabilities for this AI model. Assistants
        will not be able to "see" and process images you upload.
      </div>
      <div class="text-md text-wrap">
        We are working on adding Vision support for your AI Provider. In the meantime, you can still
        upload and use supported image files with Code Interpreter.
      </div>
    </div>
  </div>
</Modal>

<Modal
  classHeader="text-gray-700"
  class="text-gray-700"
  bind:open={visionUseImageDescriptionsModalOpen}
  autoclose
  outsideclose
>
  <div class="flex flex-col gap-5 p-4">
    <div class="flex flex-col items-center gap-2">
      <DropdownBadge
        extraClasses="border-sky-400 from-sky-100 to-sky-200 text-sky-800 text-xs uppercase"
        ><span slot="name">Experimental Feature</span></DropdownBadge
      >
      <Heading tag="h2" class="text-3xl font-semibold text-center"
        >Vision capabilities through<br />image descriptions</Heading
      >
    </div>
    <div class="flex flex-col gap-1">
      <P class="mb-4">
        Your group's Moderators have enabled an experimental feature for this Assistant that enables
        image analysis using detailed text descriptions, even though direct Vision capabilities
        aren't currently supported for this model.
      </P>

      <Heading tag="h4" class="mb-2 text-base font-semibold">What does this mean for you?</Heading>

      <List class="space-y-2 list-disc list-inside mb-4">
        <Li>
          <b>Enhanced image understanding:</b> When you upload images, PingPong provides the AI model
          with comprehensive text descriptions, allowing it to analyze and respond to image-based queries.
        </Li>
        <Li>
          <b>Seamless integration:</b> PingPong automatically converts images into detailed descriptions,
          enabling the AI to understand and discuss visual content in your conversations.
        </Li>
        <Li>
          <b>Check for important info:</b> Because this feature relies on an intermediary description,
          it is subject to the limitations of both the image captioning model and the text-based analysis.
          Expect potential inaccuracies, especially with complex or nuanced images. This is an active
          area of development.
        </Li>
      </List>

      <P>
        We appreciate your feedback as we work to improve this functionality. To share your thoughts
        or report any issues, <a
          href="https://airtable.com/appR9m6YfvPTg1H3d/pagS1VLdLrPSbeqoN/form"
          class="underline"
          rel="noopener noreferrer"
          target="_blank">use this form</a
        >.
      </P>
    </div>
  </div>
</Modal>
