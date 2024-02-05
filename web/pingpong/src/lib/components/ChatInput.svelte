<script lang="ts">
  import { writable } from 'svelte/store';
  import { ButtonGroup, Textarea, GradientButton } from 'flowbite-svelte';
  import { page } from '$app/stores';
  import { ChevronUpSolid } from 'flowbite-svelte-icons';
  import type { FileRemover, FileUploader, FileUploadInfo } from '$lib/api';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import FileUpload from '$lib/components/FileUpload.svelte';
  import { sadToast } from '$lib/toast';

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
   * Files to accept.
   */
  export let accept: string = '*/*';

  /**
   * Max upload size.
   */
  export let maxSize: number = 0;

  /**
   * Mime type lookup function.
   */
  export let mimeType: (t: string) => string;

  // Text area reference for fixing height.
  let ref;
  // Container for the list of files, for calculating height.
  let fileListRef;

  // The list of files being uploaded.
  let files = writable<FileUploadInfo[]>([]);
  $: uploading = $files.some((f) => f.state === 'pending');
  $: fileIds = $files
    .filter((f) => f.state === 'success')
    .map((f) => f.response.file_id)
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
    const fileListHeight = $files.length ? fileListRef.clientHeight : 0;
    el.style.height = `${scrollHeight + 8 + fileListHeight}px`;
    el.style.paddingTop = `${12 + fileListHeight}px`;
  };

  // Focus textarea when component is mounted. Since we can only use `use` on
  // native DOM elements, we need to wrap the textarea in a div and then
  // access its child to imperatively focus it.
  const init = (el) => {
    document.getElementById('message').focus();
    return {
      update: () => {
        document.getElementById('message').focus();
      }
    };
  };

  // Submit form when Enter (but not Shift+Enter) is pressed in textarea
  const maybeSubmit = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!disabled) {
        e.target.form.requestSubmit();
      }
    }
  };

  // Fix the height of the container when the file list changes.
  const fixFileListHeight = () => {
    const update = () => {
      const el = document.getElementById('message');
      fixHeight(el);
    };
    return { update };
  };

  // Handle updates from the file upload component.
  const handleFilesChange = (e) => {
    files = e.detail;
  };

  // Remove a file from the list / the server.
  const removeFile = (evt) => {
    const file = evt.detail;
    if (file.state === 'pending' || file.state === 'deleting') {
      return;
    } else if (file.state === 'error') {
      files.update((f) => f.filter((x) => x !== file));
    } else {
      files.update((f) => {
        const idx = f.indexOf(file);
        if (idx >= 0) {
          f[idx].state = 'deleting';
        }
        return f;
      });
      remove(file.response.id)
        .then(() => {
          files.update((f) => f.filter((x) => x !== file));
        })
        .catch(() => {
          /* no-op */
        });
    }
  };
</script>

<div
  use:init={$page.params.threadId}
  class="w-full relative rounded-lg border-[1px] border-solid border-cyan-500"
>
  <input type="hidden" name="file_ids" bind:value={fileIds} />
  <div
    class="z-10 absolute top-0 p-2 flex gap-2"
    use:fixFileListHeight={$files}
    bind:this={fileListRef}
  >
    {#each $files as file}
      <FilePlaceholder {mimeType} info={file} on:delete={removeFile} />
    {/each}
  </div>
  <div class="relative top-[2px]">
    <textarea
      id="message"
      rows="1"
      name="message"
      class="w-full !outline-none focus:ring-0 resize-none border-none bg-transparent pt-[12px] pb-[8px]"
      placeholder="Ask me anything"
      class:text-gray-700={disabled}
      class:animate-pulse={loading}
      disabled={loading || disabled}
      on:keydown={maybeSubmit}
      on:input={(e) => fixHeight(e.target)}
      style={`height: 48px; max-height: ${maxHeight}px; padding-right: 3rem; padding-left: 3.5rem; font-size: 1rem; line-height: 1.5rem;`}
    />
    <textarea
      bind:this={ref}
      style="position: absolute; visibility: hidden; height: 0px; left: -1000px; top: -1000px"
    />
    <FileUpload
      {maxSize}
      {accept}
      wrapperClass="absolute bottom-3 left-2.5"
      disabled={loading || disabled || !upload}
      upload={upload || (() => {})}
      on:error={(e) => sadToast(e.detail.message)}
      on:change={handleFilesChange}
    />
    <GradientButton
      type="submit"
      color="cyanToBlue"
      class={`${
        loading ? 'animate-pulse cursor-progress' : ''
      } w-8 h-8 p-2 absolute bottom-3 right-2.5`}
      disabled={uploading || loading || disabled}
    >
      <ChevronUpSolid size="xs" />
    </GradientButton>
  </div>
</div>
