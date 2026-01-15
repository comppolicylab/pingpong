<script module lang="ts">
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
			resetOnSubmit?: boolean;
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
			if (options.resetOnSubmit) {
				form.addEventListener('submit', reset);
			}
		}

		return {
			destroy() {
				if (!form) {
					return;
				}
				form.removeEventListener('reset', reset);
				if (options.resetOnSubmit) {
					form.removeEventListener('submit', reset);
				}
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

	interface Props {
		/**
		 * Whether to allow uploading.
		 */
		disabled?: boolean;
		/**
		 * Function to run file upload.
		 */
		upload: FileUploader;
		purpose?: FileUploadPurpose;
		useImageDescriptions?: boolean;
		/**
		 * Additional classes to apply to wrapper.
		 */
		wrapperClass?: string;
		/**
		 * File types to accept.
		 */
		accept?: string;
		/**
		 * Type of icon to display.
		 */
		type?: 'file_search' | 'code_interpreter' | 'image' | 'multimodal';
		/**
		 * Max upload size in bytes.
		 */
		maxSize?: number;
		/**
		 * Whether to support dropping files.
		 */
		drop?: boolean;
		/**
		 * Types of file search files to accept.
		 */
		fileSearchAcceptedFiles?: string | null;
		fileSearchAttachmentCount?: number;
		threadFileSearchMaxCount?: number;
		/**
		 * Types of code interpreter files to accept.
		 */
		codeInterpreterAcceptedFiles?: string | null;
		codeInterpreterAttachmentCount?: number;
		threadCodeInterpreterMaxCount?: number;
		/**
		 * Types of vision files to accept.
		 */
		visionAcceptedFiles?: string | null;
		/**
		 * Max number of file search and code interpreter files to accept.
		 */
		documentMaxCount?: number;
		currentDocumentCount?: number;
		/**
		 * Max number of vision files to accept.
		 */
		visionMaxCount?: number;
		currentVisionCount?: number;
		icon?: import('svelte').Snippet;
		label?: import('svelte').Snippet;
	}

	let {
		disabled = false,
		upload,
		purpose = 'assistants',
		useImageDescriptions = false,
		wrapperClass = '',
		accept = '*/*',
		type = 'multimodal',
		maxSize = 0,
		drop = false,
		fileSearchAcceptedFiles = null,
		fileSearchAttachmentCount = 0,
		threadFileSearchMaxCount = 0,
		codeInterpreterAcceptedFiles = null,
		codeInterpreterAttachmentCount = 0,
		threadCodeInterpreterMaxCount = 0,
		visionAcceptedFiles = null,
		documentMaxCount = 0,
		currentDocumentCount = 0,
		visionMaxCount = 0,
		currentVisionCount = 0,
		icon,
		label
	}: Props = $props();

	// Ref to the dropzone.
	let dropzone: HTMLDivElement | undefined = $state(undefined);

	// Whether the dropzone is being targeted by a file.
	let dropzoneActive = $state(false);

	// Event dispatcher for custom events.
	const dispatch = createEventDispatcher();

	// List of files being uploaded.
	const files = writable<FileUploadInfo[]>([]);

	// Reference to the file upload HTML input element.
	let uploadRef: HTMLInputElement | undefined = $state(undefined);

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
	let dropHandler = $derived(drop ? handleDropFiles : undefined);
	let dropenterHandler = $derived(drop ? handleDropEnter : undefined);
	let dropleaveHandler = $derived(drop ? handleDropLeave : undefined);
</script>

<div
	bind:this={dropzone}
	role="region"
	ondragover={(e) => e.preventDefault()}
	class={`${wrapperClass} ${drop ? 'rounded-lg border-2 border-dashed p-4' : ''} ${
		dropzoneActive ? 'border-cyan-500 bg-gray-200' : drop ? 'border-gray-300 bg-gray-100' : ''
	}`}
	ondrop={dropHandler}
	ondragenter={dropenterHandler}
	ondragleave={dropleaveHandler}
>
	<label class="flex cursor-pointer items-center justify-center">
		<input
			type="file"
			multiple
			{accept}
			style="display: none;"
			bind:this={uploadRef}
			onchange={handleFileInputChange}
			use:bindToForm={{ files: files, dispatch: dispatch }}
		/>
		<Button
			outline={!drop}
			type="button"
			color={drop ? 'alternative' : 'blue'}
			{disabled}
			class={`h-8 w-8 border-transparent bg-blue-light-40 p-1.5 ${
				drop ? 'border-transparent bg-blue-light-40' : ''
			} ${dropzoneActive ? 'animate-bounce' : ''}`}
			onclick={() => uploadRef?.click()}
		>
			{#if icon}{@render icon()}{:else if type === 'file_search'}
				<FileSearchOutline size="md" />
			{:else if type === 'image'}
				<ImageOutline size="md" />
			{:else if type === 'code_interpreter'}
				<FileCodeOutline size="md" />
			{:else}
				<PaperClipOutline size="md" />
			{/if}
		</Button>
		{@render label?.()}
	</label>
</div>
