<script lang="ts">
  import { Label, type SelectOptionType, Popover } from 'flowbite-svelte';
  import { writable, type Writable } from 'svelte/store';
  import type { FileUploader, FileUploadInfo } from '$lib/api';
  import { createEventDispatcher, onMount } from 'svelte';
  import { CloudArrowUpOutline } from 'flowbite-svelte-icons';

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

  /**
   * Max number of files to select.
   */
  export let maxCount = 10;

  /**
   * Files that are currently being uploaded.
   */
  export let uploadType: 'File Search' | 'Code Interpreter' = 'File Search';

  let loading = writable(false);

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
        dispatch('error', {
          file: f,
          message: `<strong>Upload unsuccessful: File is too large</strong><br>Max size is ${maxSize} bytes.`
        });
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

  /**
   * Handle file input change.
   */
  const handleFileInputChange = (e: Event) => {
    const input = e.target as HTMLInputElement;
    if (!input.files || !input.files.length) {
      return;
    }

    if (input.files.length + selectedFiles.length > maxCount) {
      dispatch('error', {
        message: `<strong>Upload unsuccessful: File limit reached</strong><br>You can upload up to ${availableSpace} additional ${
          availableSpace === 1 ? 'file' : 'files'
        } for ${uploadType}.${
          selectedFiles.length > 0 ? ` Remove some selected files to upload more.` : ''
        }`
      });
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

  $: availableFiles = items.filter((item) => !$value.includes(item.value));
  $: availableFileNames = availableFiles.map((item) => item.name as string);
  $: availableFileIds = availableFiles.map((item) => item.value as string);
  $: selectedFiles = items.filter((item) => $value.includes(item.value));
  $: selectedFileNames = selectedFiles.map((item) => item.name as string);
  $: selectedFileIds = selectedFiles.map((item) => item.value as string);
  let selectedAvailable: number[] = [];
  let selectedSelected: number[] = [];

  $: availableSpace = maxCount - selectedFiles.length;

  let focusedList: 'available' | 'selected' = 'available';
  let focusedIndex = -1;
  let lastClickedIndex = -1;

  let availableListElement: HTMLDivElement;
  let selectedListElement: HTMLDivElement;

  onMount(() => {
    availableListElement?.addEventListener(
      'focus',
      () => {
        focusedList = 'available';
      },
      true
    );
    selectedListElement?.addEventListener(
      'focus',
      () => {
        focusedList = 'selected';
      },
      true
    );
  });

  function moveToSelected() {
    selectedAvailable
      .sort((a, b) => a - b)
      .forEach((index) => {
        value.update((v) => [...v, availableFileIds[index]]);
      });
    selectedAvailable = [];
    focusedList = 'selected';
    focusedIndex = selectedFileNames.length - 1;
    scrollIntoView(selectedListElement, focusedIndex);
  }

  function moveToAvailable() {
    selectedSelected
      .sort((a, b) => a - b)
      .forEach((index) => {
        value.update((v) => v.filter((item) => item !== selectedFileIds[index]));
      });
    selectedSelected = [];
    focusedList = 'available';
    focusedIndex = availableFileNames.length - 1;
    scrollIntoView(availableListElement, focusedIndex);
  }

  function toggleSelection(
    list: 'available' | 'selected',
    index: number,
    event: MouseEvent | KeyboardEvent
  ) {
    const isShiftPressed = event.shiftKey;
    const isCtrlPressed = event.ctrlKey || event.metaKey;
    const currentSelected = list === 'available' ? selectedAvailable : selectedSelected;

    if (isShiftPressed && lastClickedIndex !== -1) {
      const start = Math.min(lastClickedIndex, index);
      const end = Math.max(lastClickedIndex, index);
      const newSelection = Array.from({ length: end - start + 1 }, (_, i) => start + i);

      if (list === 'available') {
        selectedAvailable = Array.from(new Set([...selectedAvailable, ...newSelection]));
        selectedSelected = [];
      } else {
        selectedSelected = Array.from(new Set([...selectedSelected, ...newSelection]));
        selectedAvailable = [];
      }
    } else if (isCtrlPressed) {
      if (list === 'available') {
        selectedAvailable = currentSelected.includes(index)
          ? currentSelected.filter((i) => i !== index)
          : [...currentSelected, index];
        selectedSelected = [];
      } else {
        selectedSelected = currentSelected.includes(index)
          ? currentSelected.filter((i) => i !== index)
          : [...currentSelected, index];
        selectedAvailable = [];
      }
    } else {
      if (list === 'available') {
        selectedAvailable = [index];
        selectedSelected = [];
      } else {
        selectedSelected = [index];
        selectedAvailable = [];
      }
    }

    lastClickedIndex = index;
    focusedList = list;
    focusedIndex = index;
    scrollIntoView(list === 'available' ? availableListElement : selectedListElement, index);
  }

  function handleKeydown(event: KeyboardEvent, list: 'available' | 'selected') {
    const isCtrlPressed = event.ctrlKey || event.metaKey;
    const currentList = list === 'available' ? availableFileNames : selectedFileNames;

    switch (event.key) {
      case 'ArrowUp':
        event.preventDefault();
        if (isCtrlPressed) {
          focusedIndex = Math.max(0, focusedIndex - 1);
        } else {
          focusedIndex = Math.max(0, focusedIndex - 1);
          toggleSelection(list, focusedIndex, event);
        }
        scrollIntoView(
          list === 'available' ? availableListElement : selectedListElement,
          focusedIndex
        );
        break;
      case 'ArrowDown':
        event.preventDefault();
        if (isCtrlPressed) {
          focusedIndex = Math.min(currentList.length - 1, focusedIndex + 1);
        } else {
          focusedIndex = Math.min(currentList.length - 1, focusedIndex + 1);
          toggleSelection(list, focusedIndex, event);
        }
        scrollIntoView(
          list === 'available' ? availableListElement : selectedListElement,
          focusedIndex
        );
        break;
      case ' ':
        if (isCtrlPressed) {
          event.preventDefault();
          toggleSelection(list, focusedIndex, event);
        }
        break;
      case 'ArrowRight':
        if (isCtrlPressed && list === 'available') {
          event.preventDefault();
          moveToSelected();
        }
        break;
      case 'ArrowLeft':
        if (isCtrlPressed && list === 'selected') {
          event.preventDefault();
          moveToAvailable();
        }
        break;
    }
  }

  function scrollIntoView(container: HTMLDivElement, index: number) {
    if (!container) return;
    const item = container.children[index] as HTMLElement;
    if (item) {
      const containerRect = container.getBoundingClientRect();
      const itemRect = item.getBoundingClientRect();

      if (itemRect.bottom > containerRect.bottom) {
        container.scrollTop += itemRect.bottom - containerRect.bottom;
      } else if (itemRect.top < containerRect.top) {
        container.scrollTop -= containerRect.top - itemRect.top;
      }
    }
  }
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
<div id={name} class="selector-container">
  <div class="column">
    <div class="label"><Label for="available-files">Available files</Label></div>
    <div
      bind:this={availableListElement}
      id="available-files"
      class="file-box"
      role="listbox"
      aria-label="Available files"
      tabindex="0"
      on:keydown={(e) => handleKeydown(e, 'available')}
    >
      {#each availableFileNames as name, index}
        <button
          type="button"
          class="file-item"
          role="option"
          aria-selected={selectedAvailable.includes(index)}
          class:selected={selectedAvailable.includes(index)}
          class:focused={focusedList === 'available' && focusedIndex === index}
          on:click={(e) => toggleSelection('available', index, e)}
        >
          {name}
        </button>
      {/each}
    </div>
  </div>
  <div class="controls">
    <button
      type="button"
      id="move-to-selected"
      class="control-button"
      on:click={moveToSelected}
      disabled={selectedAvailable.length === 0 ||
        disabled ||
        $loading ||
        selectedFiles.length + selectedAvailable.length > maxCount}
      aria-label="Move selected files to Selected list">▶</button
    >
    {#if selectedFiles.length === maxCount}
      <Popover
        class="w-64 text-sm font-light"
        title="File limit reached"
        triggeredBy="#move-to-selected"
        >You can select up to {maxCount} files to use for {uploadType}. Remove some selected files
        to add new ones.</Popover
      >
    {:else if selectedFiles.length + selectedAvailable.length > maxCount}
      <Popover
        class="w-64 text-sm font-light"
        title="File limit reached"
        triggeredBy="#move-to-selected"
        >You can select up to {availableSpace} additional {availableSpace === 1 ? 'file' : 'files'} to
        use for {uploadType}. Remove some selected files to add more.</Popover
      >
    {/if}
    <button
      type="button"
      class="control-button"
      on:click={moveToAvailable}
      disabled={selectedSelected.length === 0 || disabled || $loading}
      aria-label="Move selected files to Available list">◀</button
    >
    <button
      type="button"
      id="upload"
      class="control-button"
      on:click={() => {
        uploadRef.click();
      }}
      disabled={!upload || disabled || $loading || selectedFiles.length >= maxCount}
      aria-label="Upload files to add to your assistant"><CloudArrowUpOutline size="lg" /></button
    >
    {#if selectedFiles.length >= maxCount}
      <Popover
        class="w-64 text-sm font-light"
        title="File limit reached"
        triggeredBy="#upload"
        placement="bottom"
        >You can select up to {maxCount} files to use for {uploadType}. Remove some selected files
        to upload more.</Popover
      >
    {/if}
  </div>
  <div class="column">
    <div class="flex flex-row justify-between">
      <div class="label"><Label for="selected-files">Selected files</Label></div>
      <div class="count-label text-sm text-gray-500">
        {selectedFiles.length}/{maxCount} files selected
      </div>
    </div>
    <div
      bind:this={selectedListElement}
      id="selected-files"
      class="file-box"
      role="listbox"
      aria-label="Selected files"
      tabindex="0"
      on:keydown={(e) => handleKeydown(e, 'selected')}
    >
      {#each selectedFileNames as name, index}
        <button
          type="button"
          class="file-item"
          role="option"
          aria-selected={selectedSelected.includes(index)}
          class:selected={selectedSelected.includes(index)}
          class:focused={focusedList === 'selected' && focusedIndex === index}
          on:click={(e) => toggleSelection('selected', index, e)}
        >
          {name}
        </button>
      {/each}
    </div>
  </div>
</div>

<style>
  .selector-container {
    display: flex;
    justify-content: space-between;
  }

  .label {
    padding-left: 2px;
    padding-right: 3px;
    padding-bottom: 1px;
  }

  .count-label {
    padding-right: 3px;
    padding-bottom: 1px;
  }

  .column {
    width: 45%;
  }

  .file-box {
    border: 1px solid #ccc;
    border-radius: 4px;
    height: 200px;
    overflow-y: auto;
  }

  .file-item {
    display: block;
    font-size: 0.75rem; /* 12px */
    line-height: 1rem; /* 16px */
    width: 100%;
    padding: 3px 0px 3px 8px;
    text-align: left;
    border: none;
    background: none;
    overflow-y: auto;
    cursor: pointer;
  }

  .file-item:hover {
    background-color: #f0f0f0;
  }

  .file-item.selected {
    background-color: #1c64f2;
    color: white;
  }

  .controls {
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 0 10px;
  }

  .control-button {
    margin: 5px 0;
    padding: 5px 10px;
    background: none;
    border: 1px solid #ccc;
    border-radius: 4px;
    cursor: pointer;
  }

  .control-button:enabled:hover {
    background-color: #e7ecf5;
    color: #1c64f2;
  }

  .control-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
