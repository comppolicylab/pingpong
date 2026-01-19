<script lang="ts">
	import { Label, type SelectOptionType, Popover, Spinner, Tooltip } from 'flowbite-svelte';
	import { autoupload, bindToForm } from './FileUpload.svelte';
	import { writable, type Writable } from 'svelte/store';
	import type { FileUploader, FileUploadInfo, ServerFile } from '$lib/api';
	import { createEventDispatcher, onMount } from 'svelte';
	import {
		CloudArrowUpOutline,
		InboxFullOutline,
		LockOutline,
		LockSolid,
		UsersGroupOutline,
		UsersGroupSolid
	} from 'flowbite-svelte-icons';

	/**
	 * Name of field.
	 */
	export let name: string;

	/**
	 * Items available to select.
	 */
	export let items: SelectOptionType<string>[];
	export let privateFiles: ServerFile[];

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
		autoupload(
			Array.from(input.files),
			upload,
			files,
			maxSize,
			'assistants',
			false,
			dispatch,
			value
		);
		$loading = false;
	};
	$: privateFileIds = privateFiles.map((file) => file.file_id);
	$: availableFiles = items.filter(
		(item) => !$value.includes(item.value) && !privateFileIds.includes(item.value)
	);
	$: availableFileNames = [...availableFiles]
		.sort((a, b) => (a.name as string).localeCompare(b.name as string))
		.map((item) => item.name as string);
	$: availableFileIds = availableFiles.map((item) => item.value);
	$: selectedFiles = items.filter((item) => $value.includes(item.value));
	$: selectedFileNames = [...selectedFiles]
		.sort((a, b) => (a.name as string).localeCompare(b.name as string))
		.map((item) => [item.name as string, privateFileIds.includes(item.value)]);
	$: selectedFileIds = selectedFiles.map((item) => item.value);
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
		let privateIdsToDelete: string[] = [];
		selectedSelected
			.sort((a, b) => a - b)
			.forEach((index) => {
				value.update((v) => v.filter((item) => item !== selectedFileIds[index]));
				if (privateFileIds.includes(selectedFileIds[index])) {
					privateIdsToDelete.push(selectedFileIds[index]);
				}
			});
		dispatch(
			'delete',
			privateFiles.filter((file) => privateIdsToDelete.includes(file.file_id)).map((f) => f.id)
		);
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
	onchange={handleFileInputChange}
	use:bindToForm={{ files: files, dispatch: dispatch, resetOnSubmit: false }}
/>
<div id={name} class="flex justify-between">
	<div class="w-[45%]">
		<div class="pr-1 pb-px pl-0.5"><Label for="available-files">Available group files</Label></div>
		<div
			bind:this={availableListElement}
			id="available-files"
			class="h-[200px] overflow-y-auto rounded-sm border border-solid border-inherit"
			role="listbox"
			aria-label="Available files"
			tabindex="0"
			onkeydown={(e) => handleKeydown(e, true)}
		>
			{#each availableFileNames as name, index (name)}
				{@const isSelected = selectedAvailable.includes(index)}
				<button
					type="button"
					class="block flex w-full cursor-pointer flex-row gap-1 overflow-y-auto border-none bg-none pt-1 pr-0 pb-1 pl-2 text-left text-sm {isSelected
						? 'bg-blue-600 text-white'
						: 'hover:bg-gray-100'}"
					role="option"
					aria-selected={isSelected}
					class:focused={focusedListIsAvailable && focusedIndex === index}
					onclick={(e) => toggleSelection(true, index, e)}
				>
					{#if isSelected}
						<UsersGroupSolid />
						<Tooltip
							>This shared file is available<br />for all group members and <br />can be added to
							any assistant</Tooltip
						>
					{:else}
						<UsersGroupOutline class="text-gray-500" />
						<Tooltip
							>This shared file is available<br />for all group members and <br />can be added to
							any assistant</Tooltip
						>
					{/if}
					{name}
				</button>
			{/each}
			{#if availableFileNames.length === 0}
				<div class="flex h-full flex-col flex-wrap justify-center gap-0">
					<div class="flex justify-center">
						<InboxFullOutline class="h-20 w-20 text-gray-500" strokeWidth="1.5" />
					</div>
					<div class="text-center text-lg font-medium text-gray-500">
						{items.length > 0 ? 'All files selected' : 'No files available'}
					</div>
					<div
						class="text-md mx-14 flex flex-wrap justify-center text-center text-wrap text-gray-500"
					>
						Use the Upload Files button to upload files for your assistant.
					</div>
				</div>
			{/if}
		</div>
	</div>
	<div class="flex flex-col justify-center px-2.5 py-0">
		<button
			type="button"
			id="move-to-selected"
			class="mx-0 my-1 cursor-pointer rounded-sm border border-solid border-inherit bg-none px-2.5 py-1 enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
			onclick={moveToSelected}
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
			class="mx-0 my-1 cursor-pointer rounded-sm border border-solid border-inherit bg-none px-2.5 py-1 enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
			onclick={moveToAvailable}
			disabled={selectedSelected.length === 0 || disabled || $loading}
			aria-label="Move selected files to Available list">◀</button
		>
		<div>
			<button
				type="button"
				id="upload"
				class="mx-0 my-1 cursor-pointer rounded-sm border border-solid border-inherit bg-none px-2.5 py-1 enabled:hover:bg-slate-100 enabled:hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
				onclick={() => {
					uploadRef.click();
				}}
				disabled={!upload || disabled || $loading || selectedFiles.length >= maxCount}
				aria-label="Upload files to add to your assistant"
				>{#if uploading}<Spinner color="gray" size="6" />{:else}<CloudArrowUpOutline
						size="lg"
					/>{/if}</button
			>
			<div class="text-center text-xs text-gray-500">Upload<br />Private<br />Files</div>
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
			<div class="pr-1 pb-px pl-0.5"><Label for="selected-files">Selected files</Label></div>
			<div class="pr-1 pb-px text-sm text-gray-500">
				{selectedFiles.length}/{maxCount} files selected
			</div>
		</div>
		<div
			bind:this={selectedListElement}
			id="selected-files"
			class="h-[200px] overflow-y-auto rounded-sm border border-solid border-inherit"
			role="listbox"
			aria-label="Selected files"
			tabindex="0"
			onkeydown={(e) => handleKeydown(e, false)}
		>
			{#each selectedFileNames as [name, isPrivate], index (name)}
				{@const isSelected = selectedSelected.includes(index)}
				<button
					type="button"
					class="block flex w-full cursor-pointer flex-row gap-1 overflow-y-auto border-none bg-none pt-1 pr-0 pb-1 pl-2 text-left text-sm {isSelected
						? 'bg-blue-600 text-white'
						: 'hover:bg-gray-100'}"
					role="option"
					aria-selected={isSelected}
					class:focused={!focusedListIsAvailable && focusedIndex === index}
					onclick={(e) => toggleSelection(false, index, e)}
				>
					{#if isPrivate}
						{#if isSelected}
							<LockSolid />
							<Tooltip
								>This private file is only available to you<br />for use with this assistant</Tooltip
							>
						{:else}
							<LockOutline class="text-gray-500" />
							<Tooltip
								>This private file is only available to you<br />for use with this assistant</Tooltip
							>
						{/if}
					{:else if isSelected}
						<UsersGroupSolid />
						<Tooltip
							>This shared file is available<br />for all group members and <br />can be added to
							any assistant</Tooltip
						>
					{:else}
						<UsersGroupOutline class="text-gray-500" />
						<Tooltip
							>This shared file is available<br />for all group members and <br />can be added to
							any assistant</Tooltip
						>
					{/if}
					{name}
				</button>
			{/each}
		</div>
	</div>
</div>
