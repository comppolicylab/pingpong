<script lang="ts">
  import { Label, type SelectOptionType, Popover, Spinner } from 'flowbite-svelte';
  import { autoupload, bindToForm } from './FileUpload.svelte';
  import { writable, type Writable } from 'svelte/store';
  import type { FileUploader, FileUploadInfo } from '$lib/api';
  import { createEventDispatcher, onMount } from 'svelte';
  import { CloudArrowUpOutline, InboxFullOutline } from 'flowbite-svelte-icons';

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
  export let uploading = false;

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
    console.log('input.files', input.files.length);
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

    $loading = true;
    autoupload(Array.from(input.files), upload, files, maxSize, 'assistants', dispatch, value);
    $loading = false;
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

  let focusedListIsAvailable: boolean = true;
  let focusedIndex = -1;
  let lastClickedIndex = -1;

  let availableListElement: HTMLDivElement;
  let selectedListElement: HTMLDivElement;

  onMount(() => {
    availableListElement?.addEventListener(
      'focus',
      () => {
        focusedListIsAvailable = true;
      },
      true
    );
    selectedListElement?.addEventListener(
      'focus',
      () => {
        focusedListIsAvailable = true;
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
    focusedListIsAvailable = false;
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
    focusedListIsAvailable = true;
    focusedIndex = availableFileNames.length - 1;
    scrollIntoView(availableListElement, focusedIndex);
  }

  function toggleSelection(
    listIsAvailable: boolean,
    index: number,
    event: MouseEvent | KeyboardEvent
  ) {
    const isShiftPressed = event.shiftKey;
    const isCtrlPressed = event.ctrlKey || event.metaKey;
    const currentSelected = listIsAvailable ? selectedAvailable : selectedSelected;

    if (isShiftPressed && lastClickedIndex !== -1) {
      const start = Math.min(lastClickedIndex, index);
      const end = Math.max(lastClickedIndex, index);
      const newSelection = Array.from({ length: end - start + 1 }, (_, i) => start + i);

      if (listIsAvailable) {
        selectedAvailable = Array.from(new Set([...selectedAvailable, ...newSelection]));
        selectedSelected = [];
      } else {
        selectedSelected = Array.from(new Set([...selectedSelected, ...newSelection]));
        selectedAvailable = [];
      }
    } else if (isCtrlPressed) {
      if (listIsAvailable) {
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
      if (listIsAvailable) {
        selectedAvailable = [index];
        selectedSelected = [];
      } else {
        selectedSelected = [index];
        selectedAvailable = [];
      }
    }

    lastClickedIndex = index;
    focusedListIsAvailable = listIsAvailable;
    focusedIndex = index;
    scrollIntoView(listIsAvailable ? availableListElement : selectedListElement, index);
  }

  function handleKeydown(event: KeyboardEvent, listIsAvailable: boolean) {
    const isCtrlPressed = event.ctrlKey || event.metaKey;
    const currentList = listIsAvailable ? availableFileNames : selectedFileNames;

    switch (event.key) {
      case 'ArrowUp':
        event.preventDefault();
        if (isCtrlPressed) {
          focusedIndex = Math.max(0, focusedIndex - 1);
        } else {
          focusedIndex = Math.max(0, focusedIndex - 1);
          toggleSelection(listIsAvailable, focusedIndex, event);
        }
        scrollIntoView(listIsAvailable ? availableListElement : selectedListElement, focusedIndex);
        break;
      case 'ArrowDown':
        event.preventDefault();
        if (isCtrlPressed) {
          focusedIndex = Math.min(currentList.length - 1, focusedIndex + 1);
        } else {
          focusedIndex = Math.min(currentList.length - 1, focusedIndex + 1);
          toggleSelection(listIsAvailable, focusedIndex, event);
        }
        scrollIntoView(listIsAvailable ? availableListElement : selectedListElement, focusedIndex);
        break;
      case ' ':
        if (isCtrlPressed) {
          event.preventDefault();
          toggleSelection(listIsAvailable, focusedIndex, event);
        }
        break;
      case 'ArrowRight':
        if (listIsAvailable) {
          event.preventDefault();
          moveToSelected();
        }
        break;
      case 'ArrowLeft':
        if (!listIsAvailable) {
          event.preventDefault();
          moveToAvailable();
        }
        break;
      case 'a':
      case 'A':
        if (isCtrlPressed) {
          event.preventDefault();
          if (listIsAvailable) {
            selectedAvailable = Array.from({ length: availableFileNames.length }, (_, i) => i);
          } else {
            selectedSelected = Array.from({ length: selectedFileNames.length }, (_, i) => i);
          }
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
  use:bindToForm={{ files: files, dispatch: dispatch }}
/>
<div id={name} class="flex justify-between">
  <div class="w-[45%]">
    <div class="pl-0.5 pr-1 pb-px"><Label for="available-files">Available files</Label></div>
    <div
      bind:this={availableListElement}
      id="available-files"
      class="rounded border border-inherit border-solid h-[200px] overflow-y-auto"
      role="listbox"
      aria-label="Available files"
      tabindex="0"
      on:keydown={(e) => handleKeydown(e, true)}
    >
      {#each availableFileNames as name, index}
        {@const isSelected = selectedAvailable.includes(index)}
        <button
          type="button"
          class="block text-sm w-full pt-1 pr-0 pb-1 pl-2 border-none bg-none overflow-y-auto cursor-pointer text-left {isSelected
            ? 'text-white bg-blue-600'
            : 'hover:bg-gray-100'}"
          role="option"
          aria-selected={isSelected}
          class:focused={focusedListIsAvailable && focusedIndex === index}
          on:click={(e) => toggleSelection(true, index, e)}
        >
          {name}
        </button>
      {/each}
      {#if availableFileNames.length === 0}
        <div class="flex flex-col justify-center h-full justify-center gap-0 flex-wrap">
          <div class="flex justify-center">
            <InboxFullOutline class="h-20 w-20 text-gray-500" strokeWidth="1.5" />
          </div>
          <div class="text-lg font-medium text-gray-500 text-center">
            No {items.length > 0 ? 'more ' : ''}files available
          </div>
          <div
            class="flex justify-center text-md text-gray-500 text-center text-wrap mx-14 flex-wrap"
          >
            <div class="shrink-0">Use the Upload Files button</div>
            <CloudArrowUpOutline class="ml-1" />
            <div class="shrink-0">to upload files to your assistant.</div>
          </div>
        </div>
      {/if}
    </div>
  </div>
  <div class="flex flex-col justify-center py-0 px-2.5">
    <button
      type="button"
      id="move-to-selected"
      class="my-1 mx-0 py-1 px-2.5 bg-none rounded border border-inherit border-solid cursor-pointer enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
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
      class="my-1 mx-0 py-1 px-2.5 bg-none rounded border border-inherit border-solid cursor-pointer enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
      on:click={moveToAvailable}
      disabled={selectedSelected.length === 0 || disabled || $loading}
      aria-label="Move selected files to Available list">◀</button
    >
    <div>
      <button
        type="button"
        id="upload"
        class="my-1 mx-0 py-1 px-2.5 bg-none rounded border border-inherit border-solid cursor-pointer enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
        on:click={() => {
          uploadRef.click();
        }}
        disabled={!upload || disabled || $loading || selectedFiles.length >= maxCount}
        aria-label="Upload files to add to your assistant"
        >{#if uploading}<Spinner color="gray" size="6" />{:else}<CloudArrowUpOutline
            size="lg"
          />{/if}</button
      >
      <div class="text-xs text-center text-gray-500">Upload<br />Files</div>
    </div>
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
      <div class="pl-0.5 pr-1 pb-px"><Label for="selected-files">Selected files</Label></div>
      <div class="pr-1 pb-px text-sm text-gray-500">
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
      on:keydown={(e) => handleKeydown(e, false)}
    >
      {#each selectedFileNames as name, index}
        {@const isSelected = selectedSelected.includes(index)}
        <button
          type="button"
          class="block text-sm w-full pt-1 pr-0 pb-1 pl-2 border-none bg-none overflow-y-auto cursor-pointer text-left {isSelected
            ? 'text-white bg-blue-600'
            : 'hover:bg-gray-100'}"
          role="option"
          aria-selected={isSelected}
          class:focused={!focusedListIsAvailable && focusedIndex === index}
          on:click={(e) => toggleSelection(false, index, e)}
        >
          {name}
        </button>
      {/each}
    </div>
  </div>
</div>
