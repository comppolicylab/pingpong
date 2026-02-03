<script lang="ts">
	import { Alert, Spinner } from 'flowbite-svelte';
	import { ExclamationCircleOutline } from 'flowbite-svelte-icons';

	/**
	 * The class ID to access the video through the API
	 */
	export let classId: string;

	/**
	 * The video key/path (e.g., "lecture1.mp4" or "folder/lecture1.mp4")
	 */
	export let videoKey: string;

	export let duration: number;
	export let title: string = 'Video';
	export let videoClass: string = 'w-full rounded-lg bg-black shadow-lg';

	export let showLoading: boolean = true;

	/**
	 * Show error details
	 */
	export let showErrorDetails: boolean = true;

	let loading = true;
	let error = '';

	/**
	 * Build the API endpoint URL for streaming the video
	 */
	$: videoUrl = `/api/v1/class/${classId}/videos/${videoKey}`;

	function handleLoadedData() {
		loading = false;
	}

	function handleError(e: Event) {
		loading = false;
		const videoElement = e.target as HTMLVideoElement;
		error =
			'Failed to load video. The video might be in an unsupported format, the video key might be incorrect, or you may not have permission to access it.';
		console.error('Video loading error:', videoElement.error);
	}
</script>

<div class="relative">
	{#if showLoading && loading}
		<div class="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-gray-100">
			<Spinner size="12" color="blue" />
		</div>
	{/if}

	{#if error}
		<Alert color="red" class="mb-4">
			<ExclamationCircleOutline slot="icon" class="h-4 w-4" />
			<span class="font-medium">Video Loading Error</span>
			<p class="mt-2 text-sm">{error}</p>
			{#if showErrorDetails}
				<details class="mt-2 text-xs">
					<summary class="cursor-pointer font-medium">Troubleshooting</summary>
					<ul class="ml-4 mt-2 list-disc space-y-1">
						<li>Ensure you have permission to view videos in this class</li>
						<li>Check that the video key/path is correct</li>
						<li>Verify the video file exists in the configured video store</li>
						<li>Check that the video file format is supported (MP4, WebM, Ogg)</li>
					</ul>
				</details>
			{/if}
		</Alert>
	{/if}

	<video
		controls
		class={videoClass}
		preload="metadata"
		onloadeddata={handleLoadedData}
		onerror={handleError}
		aria-label={title}
	>
		<source src={videoUrl} type="video/mp4" />
		<track kind="captions" />
		Your browser does not support the video tag.
	</video>
</div>
