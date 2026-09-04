<script lang="ts">
	import { untrack, type Snippet } from 'svelte';

	let {
		contentKey,
		children
	}: {
		contentKey: string;
		children: Snippet<[() => void]>;
	} = $props();

	let content: HTMLDivElement;
	let retainedFrame: HTMLCanvasElement;
	let ready = $state(false);

	$effect.pre(() => {
		// Capture before Svelte removes the outgoing media. Keep the same retained
		// frame if a second navigation happens before the incoming media is ready.
		void contentKey;
		untrack(() => {
			if (ready && content && retainedFrame) {
				const source = content.querySelector('video, canvas, img');
				const width =
					source instanceof HTMLVideoElement
						? source.videoWidth
						: source instanceof HTMLImageElement
							? source.naturalWidth
							: source instanceof HTMLCanvasElement
								? source.width
								: 0;
				const height =
					source instanceof HTMLVideoElement
						? source.videoHeight
						: source instanceof HTMLImageElement
							? source.naturalHeight
							: source instanceof HTMLCanvasElement
								? source.height
								: 0;
				if (source && width && height) {
					retainedFrame.width = width;
					retainedFrame.height = height;
					retainedFrame.getContext('2d')?.drawImage(source as CanvasImageSource, 0, 0);
				}
			}
			ready = false;
		});
	});

	function markReady(key: string) {
		if (key === contentKey) ready = true;
	}
</script>

<div class="relative h-full w-full">
	<canvas
		bind:this={retainedFrame}
		aria-hidden="true"
		class="absolute inset-0 h-full w-full object-contain"
		class:invisible={ready}
	></canvas>
	<div bind:this={content} class="relative h-full w-full" class:invisible={!ready}>
		{#key contentKey}
			{@const key = contentKey}
			{@render children(() => markReady(key))}
		{/key}
	</div>
</div>
