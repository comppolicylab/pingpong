<script lang="ts">
  import { Label, type SelectOptionType, Popover } from 'flowbite-svelte';
  import { autoupload, bindToForm } from './FileUpload.svelte';
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

    autoupload(Array.from(input.files), upload, files, maxSize, 'assistants');
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
  use:bindToForm={{ files: files }}
/>
<div id={name} class="flex space-between">
  <div class="w-[45%]">
    <div class="pl-0.5 pr-[5px] pb-px"><Label for="available-files">Available files</Label></div>
    <div
      bind:this={availableListElement}
      id="available-files"
      class="rounded border border-inherit border-solid h-[200px] overflow-y-auto"
      role="listbox"
      aria-label="Available files"
      tabindex="0"
      on:keydown={(e) => handleKeydown(e, 'available')}
    >
      {#each availableFileNames as name, index}
        <button
          type="button"
          class="block text-xs w-full pt-[3px] pr-0 pb-[3px] pl-2 border-none bg-none overflow-y-auto cursor-pointer hover:bg-gray-100 selected:bg-blue-600 selected:text-white"
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
  <div class="flex flex-column justify-center py-0 px-2.5">
    <button
      type="button"
      id="move-to-selected"
      class="my-[5px] mx-0 px-[5px] py-2.5 bg-none rounded border border-inherit border-solid cursor-pointer enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:opacity-50 disabled:cursor-disabled"
      on:click={moveToSelected}
      disabled={selectedAvailable.length === 0 ||
        disabled ||
        $loading ||
        selectedFiles.length + selectedAvailable.length > maxCount}
      aria-label="Move selected files to Selected list">▶</button
    >
    {#if selectedFiles.length === maxCount && selectedAvailable.length > 0}
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
      class="my-[5px] mx-0 px-[5px] py-2.5 bg-none rounded border border-inherit border-solid cursor-pointer enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:opacity-50 disabled:cursor-disabled"
      on:click={moveToAvailable}
      disabled={selectedSelected.length === 0 || disabled || $loading}
      aria-label="Move selected files to Available list">◀</button
    >
    <button
      type="button"
      id="upload"
      class="my-[5px] mx-0 px-[5px] py-2.5 bg-none rounded border border-inherit border-solid cursor-pointer enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:opacity-50 disabled:cursor-disabled"
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
  <div class="w-[45%]">
    <div class="flex flex-row justify-between">
      <div class="pl-0.5 pr-[3px] pb-px"><Label for="selected-files">Selected files</Label></div>
      <div class="pr-[3px] pb-px text-sm text-gray-500">
        {selectedFiles.length}/{maxCount} files selected
      </div>
    </div>
    <div
      bind:this={selectedListElement}
      id="selected-files"
      class="rounded border border-inherit border-solid h-[200px] overflow-y-auto"
      role="listbox"
      aria-label="Selected files"
      tabindex="0"
      on:keydown={(e) => handleKeydown(e, 'selected')}
    >
      {#each selectedFileNames as name, index}
        <button
          type="button"
          class="block text-xs w-full pt-[3px] pr-0 pb-[3px] pl-2 border-none bg-none overflow-y-auto cursor-pointer hover:bg-gray-100 selected:bg-blue-600 selected:text-white"
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
