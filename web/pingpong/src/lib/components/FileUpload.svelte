<script lang="ts">
  import {PaperClipOutline} from 'flowbite-svelte-icons';
  import {createEventDispatcher} from "svelte";
  import {writable} from "svelte/store";
  import {Button} from "flowbite-svelte";
  import type {FileUploader, FileUploadInfo} from "$lib/api";

  /**
   * Whether to allow uploading.
   */
  export let disabled = false;

  /**
   * Function to run file upload.
   */
  export let upload: FileUploader;

  /**
   * Additional classes to apply to wrapper.
   */
  export let wrapperClass: string = "";

  /**
   * File types to accept.
   */
  export let accept = "*/*";

  /**
   * Max upload size in bytes.
   */
  export let maxSize = 0;

  // Event dispatcher for custom events.
  const dispatch = createEventDispatcher();

  // List of files being uploaded.
  const files = writable<FileUploadInfo[]>([]);

  // Reference to the file upload HTML input element.
  let uploadRef: HTMLInputElement;

  // Automatically upload files when they are selected.
  const autoupload = () => {
    if (!upload) {
      return;
    }

    // Run upload for every newly added file.
    const newFiles = Array.from(uploadRef.files).map(f => {
      if (maxSize && f.size > maxSize) {
        dispatch("error", {file: f, message: `File is too large. Max size is ${maxSize} bytes.`});
        return;
      }

      const fp = upload(f, (progress) => {
        const idx = $files.findIndex(file => file.file === f);
        if (idx !== -1) {
          $files[idx].progress = progress;
        }
      });

      // Update the file list when the upload is complete.
      fp.promise.then((result) => {
        const idx = $files.findIndex(file => file.file === f);
        if (idx !== -1) {
          $files[idx].response = result;
          $files[idx].state = "success";
          $files[idx].id = result.id;
        }
      });

      return fp;
    });

    const curFiles = $files;
    $files = [...curFiles, ...newFiles];
    dispatch("change", files);
  };

  // Make sure the input resets when the form submits.
  // The component can be used outside of a form, too.
  const bindToForm = (el: HTMLInputElement) => {
    const reset = () => {
      // Clear the file list after the form is reset or submitted.
      setTimeout(() => {
        $files = [];
        dispatch("change", files);
      }, 0);
    };
    const form = el.form;
    if (form) {
      form.addEventListener("reset", reset);
      form.addEventListener("submit", reset);
    }

    return {
      destroy() {
        if (!form) {
          return;
        }
        form.removeEventListener("reset", reset);
        form.removeEventListener("submit", reset);
      },
    };
  };
</script>

<label class="{wrapperClass} flex items-center">
  <input
    type="file"
    multiple
    accept={accept}
    style="display: none;"
    bind:this={uploadRef}
    on:change={autoupload}
    use:bindToForm
    />
  <Button
    outline
    type="button"
    color="blue"
    disabled={disabled}
    class="p-2 w-8 h-8"
    on:click={() => uploadRef.click()}
    >
    <slot name="icon">
      <PaperClipOutline size="sm" />
    </slot>
  </Button>
  <slot name="label"></slot>
</label>
