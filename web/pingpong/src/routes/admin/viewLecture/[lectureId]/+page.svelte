<script lang="ts">
	import { page } from '$app/stores';
	import { Heading, Alert, Spinner } from 'flowbite-svelte';
	import { ArrowRightOutline, ExclamationCircleOutline } from 'flowbite-svelte-icons';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { resolve } from '$app/paths';

	// Get video URL from query parameters
	$: videoUrl = $page.url.searchParams.get('url') || '';
	$: videoTitle = $page.url.searchParams.get('title') || 'Lecture Video';

	// Convert S3 URL to HTTPS if needed
	$: httpsUrl = convertS3ToHttps(videoUrl);

	let loading = true;
	let error = '';

	/**
	 * Convert s3:// URL to HTTPS URL for public buckets
	 */
	function convertS3ToHttps(url: string): string {
		if (!url) return '';

		// If it's already an HTTPS URL, return as-is
		if (url.startsWith('http://') || url.startsWith('https://')) {
			return url;
		}

		// Convert s3:// to HTTPS URL
		// Format: s3://bucket-name/path/to/file.mp4
		// Becomes: https://bucket-name.s3.amazonaws.com/path/to/file.mp4
		// Or for public CloudFront: https://your-cloudfront-domain.cloudfront.net/path
		if (url.startsWith('s3://')) {
			const withoutProtocol = url.replace('s3://', '');
			const [bucket, ...pathParts] = withoutProtocol.split('/');
			const path = pathParts.join('/');

			// For public buckets, use the standard S3 URL format
			// Note: This assumes the bucket is public or you'll need presigned URLs
			return `https://${bucket}.s3.amazonaws.com/${path}`;
		}

		return url;
	}

	function handleLoadedData() {
		loading = false;
	}

	function handleError(e: Event) {
		loading = false;
		const videoElement = e.target as HTMLVideoElement;
		error =
			'Failed to load video. The video might be in an unsupported format, the URL might be incorrect, or the bucket might not be publicly accessible.';
		console.error('Video loading error:', videoElement.error);
	}
</script>






<div class="flex h-full w-full flex-col">
	<PageHeader>
		<div slot="left">
			<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">
				{videoTitle}
			</h2>
		</div>
		<div slot="right">
			<a
				href={resolve(`/admin`)}
				class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
			>
				Admin page <ArrowRightOutline size="md" class="text-orange" />
			</a>
		</div>
	</PageHeader>

	<div class="h-full w-full overflow-y-auto p-12">
		<div class="mx-auto max-w-5xl">
			<div class="mb-6">
				<Heading tag="h3" class="text-dark-blue-40 font-serif text-2xl font-medium">
					{videoTitle}
				</Heading>
			</div>

			{#if !videoUrl}
				<Alert color="yellow" class="mb-6">
					<ExclamationCircleOutline slot="icon" class="h-4 w-4" />
					<span class="font-medium">No video URL provided</span>
					<p class="mt-2 text-sm">
						Please provide a video URL using the <code class="rounded bg-gray-200 px-1"
							>?url=</code
						> query parameter.
					</p>
					<p class="mt-2 text-sm">
						Example: <code class="rounded bg-gray-200 px-1 text-xs"
							>/admin/viewLecture?url=https://your-video-url.mp4&title=My%20Lecture</code
						>
					</p>
				</Alert>
			{:else}
				<div class="relative mb-6">
					{#if loading}
						<div
							class="absolute inset-0 z-10 flex items-center justify-center bg-gray-100 rounded-lg"
						>
							<Spinner size="12" color="blue" />
						</div>
					{/if}

					{#if error}
						<Alert color="red" class="mb-6">
							<ExclamationCircleOutline slot="icon" class="h-4 w-4" />
							<span class="font-medium">Video Loading Error</span>
							<p class="mt-2 text-sm">{error}</p>
							<details class="mt-2 text-xs">
								<summary class="cursor-pointer font-medium">Troubleshooting</summary>
								<ul class="ml-4 mt-2 list-disc space-y-1">
									<li>Ensure the S3 bucket is publicly accessible or use a presigned URL</li>
									<li>Check that the video file format is supported (MP4, WebM, Ogg)</li>
									<li>Verify CORS settings allow your domain to access the video</li>
									<li>
										For private buckets, generate a presigned URL and pass it as the URL parameter
									</li>
								</ul>
							</details>
						</Alert>
					{/if}

					<video
						controls
						class="w-full rounded-lg bg-black shadow-lg"
						preload="metadata"
						onloadeddata={handleLoadedData}
						onerror={handleError}
					>
						<source src={httpsUrl} type="video/mp4" />
						<track kind="captions" />
						Your browser does not support the video tag.
					</video>
				</div>

				<div class="rounded-lg bg-blue-light-40 p-4 text-sm">
					<p class="mb-2 font-medium text-blue-dark-50">Video Information:</p>
					<div class="space-y-1 text-blue-dark-40">
						<p><span class="font-medium">Source:</span> {httpsUrl}</p>
						{#if videoUrl.startsWith('s3://')}
							<p class="text-xs text-orange">
								<ExclamationCircleOutline class="mr-1 inline h-3 w-3" />
								Note: S3 URL was converted to HTTPS. Ensure the bucket is publicly accessible.
							</p>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>
