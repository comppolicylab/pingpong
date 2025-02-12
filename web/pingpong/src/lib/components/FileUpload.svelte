<script context="module" lang="ts">
  // Automatically upload files when they are selected.
  export const autoupload = (
    toUpload: File[],
    upload: FileUploader,
    files: Writable<FileUploadInfo[]>,
    maxSize = 0,
    purpose: FileUploadPurpose = 'assistants',
    useImageDescriptions: boolean = false,
    dispatch: (
      type: string,
      detail: { file: File; message: string } | Writable<FileUploadInfo[]>
    ) => void,
    value?: Writable<string[]>,
    inputRef?: HTMLInputElement
  ) => {
    if (!upload) {
      return;
    }

    // Run upload for every newly added file.
    const newFiles: FileUploadInfo[] = [];
    toUpload.forEach((f) => {
      if (maxSize && f.size > maxSize) {
        const maxUploadSize = humanSize(maxSize);
        dispatch('error', {
          file: f,
          message: `<strong>Upload unsuccessful: File is too large</strong><br>Max size is ${maxUploadSize}.`
        });
        return;
      }

      const fp = upload(
        f,
        (progress) => {
          files.update((existingFiles) => {
            const idx = existingFiles.findIndex((file) => file.file === f);
            if (idx !== -1) {
              existingFiles[idx].progress = progress;
            }
            return existingFiles;
          });
        },
        purpose,
        useImageDescriptions
      );

      // Update the file list when the upload is complete.
      fp.promise
        .then((result) => {
          files.update((existingFiles) => {
            const idx = existingFiles.findIndex((file) => file.file === f);
            if (idx !== -1) {
              existingFiles[idx].response = result;
              existingFiles[idx].state = 'success';
            }
            return existingFiles;
          });
          if ('id' in result && value) {
            value.update((existing) => [...existing, result.file_id]);
          }
        })
        .catch((error) => {
          files.update((existingFiles) => {
            const idx = existingFiles.findIndex((file) => file.file === f);
            if (idx !== -1) {
              existingFiles[idx].response = error;
              existingFiles[idx].state = 'error';
            }
            return existingFiles;
          });
          dispatch('error', {
            file: f,
            message: `Could not upload file ${f.name}: ${error.error.detail || 'unknown error'}`
          });
        });

      newFiles.push(fp);
    });

    files.update((existingFiles) => [...existingFiles, ...newFiles]);
    dispatch('change', files);

    if (inputRef) {
      inputRef.value = '';
    }
  };

  // Make sure the input resets when the form submits.
  // The component can be used outside of a form, too.
  export const bindToForm = (
    el: HTMLInputElement,
    options: {
      files: Writable<FileUploadInfo[]>;
      dispatch: (
        type: string,
        detail: { file: File; message: string } | Writable<FileUploadInfo[]>
      ) => void;
    }
  ) => {
    const reset = () => {
      // Clear the file list after the form is reset or submitted.
      setTimeout(() => {
        options.files.set([]);
        options.dispatch('change', options.files);
      }, 0);
    };
    const form = el.form;
    if (form) {
      form.addEventListener('reset', reset);
      form.addEventListener('submit', reset);
    }

    return {
      destroy() {
        if (!form) {
          return;
        }
        form.removeEventListener('reset', reset);
        form.removeEventListener('submit', reset);
      }
    };
  };
</script>

<script lang="ts">
  // Could also consider using CodeOutline, SearchOutline
  import {
    FileCodeOutline,
    FileSearchOutline,
    ImageOutline,
    PaperClipOutline
  } from 'flowbite-svelte-icons';
  import { createEventDispatcher } from 'svelte';
  import { writable, type Writable } from 'svelte/store';
  import { Button } from 'flowbite-svelte';
  import type { FileUploader, FileUploadInfo, FileUploadPurpose } from '$lib/api';
  import { humanSize } from '$lib/size';
  /**
   * Whether to allow uploading.
   */
  export let disabled = false;

  /**
   * Function to run file upload.
   */
  export let upload: FileUploader;

  export let purpose: FileUploadPurpose = 'assistants';

  export let useImageDescriptions: boolean = false;

  /**
   * Additional classes to apply to wrapper.
   */
  export let wrapperClass: string = '';

  /**
   * File types to accept.
   */
  export let accept = '*/*';

  /**
   * Type of icon to display.
   */
  export let type: 'file_search' | 'code_interpreter' | 'image' | 'multimodal' = 'multimodal';

  /**
   * Max upload size in bytes.
   */
  export let maxSize = 0;

  /**
   * Whether to support dropping files.
   */
  export let drop = false;

  /**
   * Types of file search files to accept.
   */
  export let fileSearchAcceptedFiles: string | null = null;
  export let fileSearchAttachmentCount = 0;
  export let threadFileSearchMaxCount = 0;

  /**
   * Types of code interpreter files to accept.
   */
  export let codeInterpreterAcceptedFiles: string | null = null;
  export let codeInterpreterAttachmentCount = 0;
  export let threadCodeInterpreterMaxCount = 0;

  /**
   * Types of vision files to accept.
   */
  export let visionAcceptedFiles: string | null = null;

  /**
   * Max number of file search and code interpreter files to accept.
   */
  export let documentMaxCount = 0;
  export let currentDocumentCount = 0;

  /**
   * Max number of vision files to accept.
   */
  export let visionMaxCount = 0;
  export let currentVisionCount = 0;

  // Ref to the dropzone.
  let dropzone: HTMLDivElement;

  // Whether the dropzone is being targeted by a file.
  let dropzoneActive = false;

  // Event dispatcher for custom events.
  const dispatch = createEventDispatcher();

  // List of files being uploaded.
  const files = writable<FileUploadInfo[]>([]);

  // Reference to the file upload HTML input element.
  let uploadRef: HTMLInputElement;

  /**
   * Handle file drop.
   */
  const handleDropFiles = (e: DragEvent) => {
    dropzoneActive = false;
    e.preventDefault();
    e.stopPropagation();
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) {
      return;
    }

    autoupload(
      Array.from(e.dataTransfer.files),
      upload,
      files,
      maxSize,
      purpose,
      useImageDescriptions,
      dispatch
    );
  };

  /**
   * Handle file input change.
   */
  const handleFileInputChange = (e: Event) => {
    const input = e.target as HTMLInputElement;
    if (!input.files || !input.files.length) {
      return;
    }

    let numberOfDocumentFiles = 0;
    let numberOfFileSearchFiles = 0;
    let numberOfCodeInterpreterFiles = 0;
    let numberOfVisionFiles = 0;

    for (let i = 0; i < input.files.length; i++) {
      const file = input.files[i];
      if (
        (fileSearchAcceptedFiles && fileSearchAcceptedFiles.includes(file.type)) ||
        (codeInterpreterAcceptedFiles && codeInterpreterAcceptedFiles.includes(file.type))
      ) {
        numberOfDocumentFiles++;
      }
      if (fileSearchAcceptedFiles && fileSearchAcceptedFiles.includes(file.type)) {
        numberOfFileSearchFiles++;
      }
      if (codeInterpreterAcceptedFiles && codeInterpreterAcceptedFiles.includes(file.type)) {
        numberOfCodeInterpreterFiles++;
      }
      if (visionAcceptedFiles && visionAcceptedFiles.includes(file.type)) {
        numberOfVisionFiles++;
      }
    }

    let fileCounts = {
      document: [numberOfDocumentFiles, currentDocumentCount, documentMaxCount],
      images: [numberOfVisionFiles, currentVisionCount, visionMaxCount]
    };

    for (const [key, value] of Object.entries(fileCounts)) {
      if (value[0] > value[2] - value[1]) {
        dispatch('error', {
          message: `<strong>Upload unsuccessful: Message attachment limit reached</strong><br>You can upload up to ${value[2] - value[1]} additional ${key} ${
            value[2] - value[1] === 1 ? 'attachment' : 'attachments'
          } in this message.${value[1] > 0 ? ` Remove some uploaded files from your message to upload more.` : ''}`
        });
        return;
      }
    }

    if (
      threadFileSearchMaxCount &&
      numberOfFileSearchFiles + fileSearchAttachmentCount > threadFileSearchMaxCount
    ) {
      dispatch('error', {
        message: `<strong>Upload unsuccessful: Thread file limit reached</strong><br>You can upload up to ${threadFileSearchMaxCount - fileSearchAttachmentCount} additional file ${
          threadFileSearchMaxCount - fileSearchAttachmentCount === 1 ? 'attachment' : 'attachments'
        } in this thread.${fileSearchAttachmentCount > 0 ? ` Remove some uploaded files from this thread or message to upload more.` : ''}`
      });
      return;
    }

    if (
      threadCodeInterpreterMaxCount &&
      numberOfCodeInterpreterFiles + codeInterpreterAttachmentCount > threadCodeInterpreterMaxCount
    ) {
      dispatch('error', {
        message: `<strong>Upload unsuccessful: Thread file limit reached</strong><br>You can upload up to ${
          threadCodeInterpreterMaxCount - codeInterpreterAttachmentCount
        } additional file ${
          threadCodeInterpreterMaxCount - codeInterpreterAttachmentCount === 1
            ? 'attachment'
            : 'attachments'
        } in this thread.${codeInterpreterAttachmentCount > 0 ? ` Remove some uploaded files from this thread or message to upload more.` : ''}`
      });
      return;
    }

    autoupload(
      Array.from(input.files),
      upload,
      files,
      maxSize,
      purpose,
      useImageDescriptions,
      dispatch,
      undefined,
      uploadRef
    );
  };

  // Due to how drag events are handled on child elements, we need to keep
  // track of the stack of events to determine when the dropzone is fully
  // exited. Otherwise there is an edge case where the dropzone is still
  // active when dragging out of the browser into a desktop window that is
  // partially covering the dropzone.
  let dragCounter = 0;

  /**
   * Handle mouse leaving the dropzone.
   */
  const handleDropLeave = (e: DragEvent) => {
    dragCounter--;
    if (dragCounter === 0) {
      dropzoneActive = false;
    }
    e.preventDefault();
    e.stopPropagation();
  };

  /**
   * Handle mouse entering the dropzone.
   */
  const handleDropEnter = (e: DragEvent) => {
    dragCounter++;
    dropzoneActive = true;
    e.preventDefault();
    e.stopPropagation();
  };

  // Set the drop handler according to whether drop is enabled.
  $: dropHandler = drop ? handleDropFiles : undefined;
  $: dropenterHandler = drop ? handleDropEnter : undefined;
  $: dropleaveHandler = drop ? handleDropLeave : undefined;
</script>

<div
  bind:this={dropzone}
  role="region"
  on:dragover={(e) => e.preventDefault()}
  class={`${wrapperClass} ${drop ? 'border-dashed border-2 rounded-lg p-4' : ''} ${
    dropzoneActive ? 'bg-gray-200 border-cyan-500' : drop ? 'bg-gray-100 border-gray-300' : ''
  }`}
  on:drop={dropHandler}
  on:dragenter={dropenterHandler}
  on:dragleave={dropleaveHandler}
>
  <label class="flex items-center justify-center cursor-pointer">
    <input
      type="file"
      multiple
      {accept}
      style="display: none;"
      bind:this={uploadRef}
      on:change={handleFileInputChange}
      use:bindToForm={{ files: files, dispatch: dispatch }}
    />
    <Button
      outline={!drop}
      type="button"
      color={drop ? 'alternative' : 'blue'}
      {disabled}
      class={`p-1.5 w-8 h-8 bg-blue-light-40 border-transparent ${
        drop ? 'bg-blue-light-40 border-transparent' : ''
      } ${dropzoneActive ? 'animate-bounce' : ''}`}
      on:click={() => uploadRef.click()}
    >
      <slot name="icon">
        {#if type === 'file_search'}
          <FileSearchOutline size="md" />
        {:else if type === 'image'}
          <ImageOutline size="md" />
        {:else if type === 'code_interpreter'}
          <FileCodeOutline size="md" />
        {:else}
          <PaperClipOutline size="md" />
        {/if}
      </slot>
    </Button>
    <slot name="label" />
  </label>
</div>
