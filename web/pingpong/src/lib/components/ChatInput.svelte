<script lang="ts" context="module">
  export type ChatInputMessage = {
    code_interpreter_file_ids: string[];
    file_search_file_ids: string[];
    message: string;
    callback?: () => void;
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

  const dispatcher = createEventDispatcher();

  /**
   * Whether to allow sending.
   */
  export let disabled = false;
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
   * Max upload size.
   */
  export let maxSize: number = 0;

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
  let codeInterpreterFileListRef: HTMLDivElement;
  let fileSearchFileListRef: HTMLDivElement;

  // The list of files being uploaded.
  let codeInterpreterFiles = writable<FileUploadInfo[]>([]);
  $: uploadingCodeInterpreter = $codeInterpreterFiles.some((f) => f.state === 'pending');
  $: codeInterpreterFileIds = $codeInterpreterFiles
    .filter((f) => f.state === 'success')
    .map((f) => (f.response as ServerFile).file_id)
    .join(',');

  let fileSearchFiles = writable<FileUploadInfo[]>([]);
  $: uploadingFileSearch = $fileSearchFiles.some((f) => f.state === 'pending');
  $: fileSearchFileIds = $fileSearchFiles
    .filter((f) => f.state === 'success')
    .map((f) => (f.response as ServerFile).file_id)
    .join(',');

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
    if (!ref.value || disabled) {
      return;
    }
    const message = ref.value;
    $codeInterpreterFiles = [];
    $fileSearchFiles = [];
    console.log('submitting', code_interpreter_file_ids, file_search_file_ids, message);
    dispatcher('submit', {
      file_search_file_ids,
      code_interpreter_file_ids,
      message,
      callback: () => {
        document.getElementById('message')?.focus();
      }
    });
    ref.value = '';
    realRef.value = '';
    fixHeight(realRef);
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
  const handleCodeInterpreterFilesChange = (e: CustomEvent<Writable<FileUploadInfo[]>>) => {
    codeInterpreterFiles = e.detail;
  };

  const handleFileSearchFilesChange = (e: CustomEvent<Writable<FileUploadInfo[]>>) => {
    fileSearchFiles = e.detail;
  };

  // Remove a file from the list / the server.
  const removeFileSearchFile = (evt: CustomEvent<FileUploadInfo>) => {
    if (!remove) {
      return;
    }
    const file = evt.detail;
    if (file.state === 'pending' || file.state === 'deleting') {
      return;
    } else if (file.state === 'error') {
      fileSearchFiles.update((f) => f.filter((x) => x !== file));
    } else {
      fileSearchFiles.update((f) => {
        const idx = f.indexOf(file);
        if (idx >= 0) {
          f[idx].state = 'deleting';
        }
        return f;
      });
      remove((file.response as ServerFile).id)
        .then(() => {
          fileSearchFiles.update((f) => f.filter((x) => x !== file));
        })
        .catch(() => {
          /* no-op */
        });
    }
  };

  const removeCodeInterpreterFile = (evt: CustomEvent<FileUploadInfo>) => {
    if (!remove) {
      return;
    }
    const file = evt.detail;
    if (file.state === 'pending' || file.state === 'deleting') {
      return;
    } else if (file.state === 'error') {
      codeInterpreterFiles.update((f) => f.filter((x) => x !== file));
    } else {
      codeInterpreterFiles.update((f) => {
        const idx = f.indexOf(file);
        if (idx >= 0) {
          f[idx].state = 'deleting';
        }
        return f;
      });
      remove((file.response as ServerFile).id)
        .then(() => {
          codeInterpreterFiles.update((f) => f.filter((x) => x !== file));
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
  <input type="hidden" name="file_search_file_ids" bind:value={fileSearchFileIds} />
  <div
    class="z-10 top-0 p-2 flex gap-2 flex-wrap"
    use:fixFileListHeight={$fileSearchFiles}
    bind:this={fileSearchFileListRef}
  >
    {#each $fileSearchFiles as file}
      <FilePlaceholder {mimeType} info={file} on:delete={removeFileSearchFile} />
    {/each}
  </div>
  <input type="hidden" name="code_interpreter_file_ids" bind:value={codeInterpreterFileIds} />
  <div
    class="z-10 top-0 p-2 flex gap-2 flex-wrap"
    use:fixFileListHeight={$codeInterpreterFiles}
    bind:this={codeInterpreterFileListRef}
  >
    {#each $codeInterpreterFiles as file}
      <FilePlaceholder {mimeType} info={file} on:delete={removeCodeInterpreterFile} />
    {/each}
  </div>
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
      placeholder="Ask me anything"
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
    {#if upload}
      <FileUpload
        {maxSize}
        accept={fileSearchAcceptedFiles || ''}
        disabled={loading || disabled || !upload || !fileSearchAcceptedFiles}
        type="file_search"
        {upload}
        on:error={(e) => sadToast(e.detail.message)}
        on:change={handleFileSearchFilesChange}
      />
      {#if fileSearchAcceptedFiles}
        <Popover arrow={false}>Add files for File Search</Popover>
      {:else}
        <Popover arrow={false}>File Search is disabled</Popover>
      {/if}
    {/if}
    {#if upload}
      <FileUpload
        {maxSize}
        accept={codeInterpreterAcceptedFiles || ''}
        disabled={loading || disabled || !upload || !codeInterpreterAcceptedFiles}
        type="code_interpreter"
        {upload}
        on:error={(e) => sadToast(e.detail.message)}
        on:change={handleCodeInterpreterFilesChange}
      />
      {#if codeInterpreterAcceptedFiles}
        <Popover arrow={false}>Add files for Code Interpreter</Popover>
      {:else}
        <Popover arrow={false}>Code Interpreter is disabled</Popover>
      {/if}
    {/if}
    <Button
      pill
      on:click={submit}
      on:touchstart={submit}
      on:keydown={maybeSubmit}
      class={`${
        loading ? 'animate-pulse cursor-progress' : ''
      } p-3 px-4 mr-2 bg-orange hover:bg-orange-dark`}
      disabled={uploadingCodeInterpreter || uploadingFileSearch || loading || disabled}
    >
      Submit
    </Button>
  </div>
</div>
