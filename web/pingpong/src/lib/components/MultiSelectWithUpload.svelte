<script lang="ts">
  import { MultiSelect, type SelectOptionType } from 'flowbite-svelte';
  import { writable, type Writable } from 'svelte/store';
  import type { FileUploader, FileUploadInfo, ServerFile } from '$lib/api';
  import { createEventDispatcher } from 'svelte';

  /**
   * Name of field.
   */
  export let name: string;

  /**
   * Items available to select.
   */
  export let items: SelectOptionType<string>[];

  /**
   * File ids of selected items.
   */
  export let value: Writable<string[]>;

  /**
   * Whether to allow uploading.
   */
  export let disabled = false;

  /**
   * Function to run file upload.
   */
  export let upload: FileUploader;

  /**
   * File types to accept.
   */
  export let accept = '*/*';

  /**
   * Max upload size in bytes.
   */
  export let maxSize = 0;

  let loading = writable(false);
  export let uploadingOptimistic = false;

  /**
   * Add more files placeholder.
   */
  $: addMoreFilesOption = !($loading || uploadingOptimistic)
    ? { name: '+ Add more files', value: 'add_more_files' }
    : { name: 'Uploading files...', value: 'uploading_files' };

  // List of files being uploaded.
  const files = writable<FileUploadInfo[]>([]);

  // Event dispatcher for custom events.
  const dispatch = createEventDispatcher();

  // Reference to the file upload HTML input element.
  let uploadRef: HTMLInputElement;

  // Automatically upload files when they are selected.
  const autoupload = (toUpload: File[]) => {
    $loading = true;
    if (!upload) {
      $loading = false;
      return;
    }

    // Run upload for every newly added file.
    const newFiles: FileUploadInfo[] = [];
    toUpload.forEach((f) => {
      if (maxSize && f.size > maxSize) {
        dispatch('error', { file: f, message: `File is too large. Max size is ${maxSize} bytes.` });
        return;
      }

      const fp = upload(
        f,
        (progress) => {
          const idx = $files.findIndex((file) => file.file === f);
          if (idx !== -1) {
            $files[idx].progress = progress;
          }
        },
        'assistants'
      );

      // Update the file list when the upload is complete.
      fp.promise
        .then((result) => {
          const idx = $files.findIndex((file) => file.file === f);
          if (idx !== -1) {
            $files[idx].response = result;
            $files[idx].state = 'success';
          }
          if ('id' in result) {
            value.update((v) => [...v, result.file_id]);
          }
        })
        .catch((error) => {
          const idx = $files.findIndex((file) => file.file === f);
          if (idx !== -1) {
            $files[idx].response = error;
            $files[idx].state = 'error';
          }
          dispatch('error', { file: f, message: `Could not upload file ${f.name}: ${error}.` });
        });

      newFiles.push(fp);
    });

    const curFiles = $files;
    $files = [...curFiles, ...newFiles];
    $loading = false;
    dispatch('change', files);
  };
  $: {
    if ($value.includes('add_more_files')) {
      uploadRef.click();
      value.update((v) => v.filter((item) => item !== 'add_more_files'));
    }
  }
  /**
   * Handle file input change.
   */
  const handleFileInputChange = (e: Event) => {
    const input = e.target as HTMLInputElement;
    if (!input.files || !input.files.length) {
      return;
    }

    autoupload(Array.from(input.files));
  };

  // Make sure the input resets when the form submits.
  // The component can be used outside of a form, too.
  const bindToForm = (el: HTMLInputElement) => {
    const reset = () => {
      // Clear the file list after the form is reset or submitted.
      setTimeout(() => {
        $files = [];
        dispatch('change', files);
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

<input
  type="file"
  multiple
  {accept}
  style="display: none;"
  bind:this={uploadRef}
  on:change={handleFileInputChange}
  use:bindToForm
/>
<MultiSelect
  {name}
  items={!disabled ? [addMoreFilesOption, ...items] : items}
  bind:value={$value}
/>
