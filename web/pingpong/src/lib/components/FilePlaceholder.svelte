<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import type {
		MimeTypeLookupFn,
		FileUploadInfo,
		FileUploadFailure,
		FileUploadPurpose
	} from '$lib/api';
	import {
		CloseOutline,
		FileSolid,
		ExclamationCircleOutline,
		ImageSolid
	} from 'flowbite-svelte-icons';
	import { Tooltip, Button } from 'flowbite-svelte';
	import ProgressCircle from './ProgressCircle.svelte';
	import { Jumper } from 'svelte-loading-spinners';

	
	interface Props {
		/**
		 * Information about a file that is being uploaded.
		 */
		info: FileUploadInfo;
		purpose?: FileUploadPurpose;
		mimeType: MimeTypeLookupFn;
		preventDeletion?: boolean;
	}

	let {
		info,
		purpose = 'assistants',
		mimeType,
		preventDeletion = false
	}: Props = $props();

	// Custom events
	const dispatch = createEventDispatcher();

	// Look up info about the file type.
	const nameForMimeType = (type: string) => {
		const mime = mimeType(type);
		return mime?.name || 'Unsupported!';
	};

	let progress = $derived(info.progress);
	let type = $derived(nameForMimeType(info.file.type));
	let name = $derived(info.file.name);
	let state = $derived(info.state);
	let error = $derived(info.state === 'error' ? (info.response as FileUploadFailure).error : '');

	// Delete button clicked.
	const deleteFile = () => {
		dispatch('delete', info);
	};
</script>

<div
	class="-delete-button-container relative flex cursor-default items-center rounded-lg border-[1px] border-solid border-gray-300 bg-white px-2 hover:shadow-sm"
>
	<div>
		{#if state === 'pending'}
			{#if progress < 100}
				<ProgressCircle {progress} />
			{:else}
				<Jumper size="20" color="#0ea5e9" />
			{/if}
		{:else if state === 'deleting' && purpose === 'vision'}
			<ImageSolid class="h-6 w-6 animate-pulse text-red-500" />
		{:else if state === 'deleting' && purpose !== 'vision'}
			<FileSolid class="h-6 w-6 animate-pulse text-red-500" />
		{:else if state === 'success' && purpose === 'vision'}
			<ImageSolid class="h-6 w-6 text-green-500" />
		{:else if state === 'success' && purpose !== 'vision'}
			<FileSolid class="h-6 w-6 text-green-500" />
		{:else}
			<ExclamationCircleOutline class="h-6 w-6 text-red-500" />
			<Tooltip>Upload Error: {typeof error === 'string' ? error : error.detail}</Tooltip>
		{/if}
	</div>
	<div class="flex flex-col p-2">
		<div class="text-xs font-bold text-gray-500">{name}</div>
		<div class="text-xs text-gray-500">{type}</div>
	</div>
	{#if state !== 'pending' && state !== 'deleting'}
		{#if !preventDeletion}
			<div class="-delete-button absolute top-[-6px] right-[-6px]">
				<Button pill color="dark" class="p-0" onclick={deleteFile}>
					<CloseOutline class="h-4 w-4" />
				</Button>
			</div>
		{:else if preventDeletion && purpose === 'vision'}
			<Tooltip arrow={false} class="w-64 font-light"
				>This file is an image file and cannot be removed from the conversation. Delete the Thread
				to remove it.</Tooltip
			>
		{/if}
	{/if}
</div>

<style lang="css">
	.-delete-button {
		display: none;
	}
	.-delete-button-container:hover .-delete-button {
		display: block !important;
	}
</style>
