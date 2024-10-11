<script lang="ts" context="module">
  export type ChatInputMessage = {
    code_interpreter_file_ids: string[];
    file_search_file_ids: string[];
    vision_file_ids: string[];
    message: string;
    callback: (success: boolean) => void;
  };
</script>

<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { writable } from 'svelte/store';
  import type { Writable } from 'svelte/store';
  import { Button, Popover } from 'flowbite-svelte';
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
  /**
   * Files to accept for code interpreter. If null, code interpreter is disabled.
   */
  export let codeInterpreterAcceptedFiles: string | null = null;
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
  $: codeInterpreterFileIds = $allFiles
    .filter((f) => f.state === 'success' && (f.response as ServerFile).code_interpreter_file_id)
    .map((f) => (f.response as ServerFile).file_id)
    .join(',');

  $: fileSearchFileIds = $allFiles
    .filter((f) => f.state === 'success' && (f.response as ServerFile).file_search_file_id)
    .map((f) => (f.response as ServerFile).file_id)
    .join(',');

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
    const message = ref.value;
    dispatcher('submit', {
      file_search_file_ids,
      code_interpreter_file_ids,
      vision_file_ids,
      message,
      callback: (success: boolean) => {
        if (success) {
          $allFiles = [];
          document.getElementById('message')?.focus();
          ref.value = '';
          realRef.value = '';
          fixHeight(realRef);
        }
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
  {#if $allFiles.length > 0}
    <div
      class="z-10 top-0 p-2 flex gap-2 flex-wrap"
      use:fixFileListHeight={$allFiles}
      bind:this={allFileListRef}
    >
      {#each $allFiles as file}
        <FilePlaceholder {mimeType} info={file} purpose="multimodal" on:delete={removeFile} />
      {/each}
    </div>
  {/if}
  <div
    class="relative flex gap-3 items-center p-2 rounded-full bg-blue-light-50 shadow-inner w-full"
    bind:this={containerRef}
  >
    <textarea
      bind:this={realRef}
      id="message"
      rows="1"
      name="message"
      class="w-full !outline-none focus:ring-0 resize-none border-none bg-transparent pt-[12px] pb-[10px] pl-2 sm:pl-6 pr-2 sm:pr-8"
      placeholder={canSubmit
        ? 'Ask me anything'
        : assistantDeleted
          ? 'Read-only thread: the assistant associated with this thread is deleted.'
          : canViewAssistant
            ? 'Read-only thread: You no longer have permissions to interact with this assistant.'
            : "You can't reply in this thread."}
      class:text-gray-700={disabled}
      class:animate-pulse={loading}
      disabled={loading || disabled}
      on:keydown={maybeSubmit}
      on:input={handleTextAreaInput}
      style={`height: 48px; max-height: ${maxHeight}px; font-size: 1rem; line-height: 1.5rem;`}
    />
    <textarea
      bind:this={ref}
      style="position: absolute; visibility: hidden; height: 0px; left: -1000px; top: -1000px"
    />
    <div class="flex flex-row gap-1.5">
      {#if upload && purpose}
        <FileUpload
          {maxSize}
          accept={(attachments.length >= 10 ? '' : (codeInterpreterAcceptedFiles ?? '')) +
            (attachments.length >= 10 ? '' : (fileSearchAcceptedFiles ?? '')) +
            (visionFileIds.length >= 10 ? '' : (visionAcceptedFiles ?? ''))}
          disabled={loading ||
            disabled ||
            !upload ||
            (attachments.length >= 10 && visionFileIds.length >= 10)}
          type="multimodal"
          {purpose}
          {upload}
          on:error={(e) => sadToast(e.detail.message)}
          on:change={handleFilesChange}
        />
        {#if (codeInterpreterAcceptedFiles || fileSearchAcceptedFiles || visionAcceptedFiles) && !(attachments.length >= 10 || visionFileIds.length >= 10) && !(loading || disabled || !upload)}
          <Popover defaultClass="py-2 px-3 max-w-56" arrow={false}>Upload files to thread.</Popover>
        {:else if attachments.length >= 10}
          <Popover defaultClass="py-2 px-3 max-w-56" arrow={false}
            >Maximum number of document attachments reached{visionFileIds.length < 10
              ? '. You can still upload images.'
              : ''}</Popover
          >
        {:else if visionFileIds.length >= 10}
          <Popover defaultClass="py-2 px-3 max-w-56" arrow={false}
            >Maximum number of image uploads reached. You can still upload documents.</Popover
          >
        {:else}
          <Popover arrow={false}>File upload is disabled</Popover>
        {/if}
      {/if}
    </div>
    <Button
      pill
      on:click={submit}
      on:touchstart={submit}
      on:keydown={maybeSubmit}
      class={`${
        loading ? 'animate-pulse cursor-progress' : ''
      } p-3 px-4 mr-2 bg-orange hover:bg-orange-dark`}
      disabled={uploading || loading || disabled}
    >
      Submit
    </Button>
  </div>
</div>
