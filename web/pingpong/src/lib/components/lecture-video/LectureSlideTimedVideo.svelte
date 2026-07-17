<script lang="ts">
	let {
		src,
		offsetMs,
		startOffsetMs,
		endOffsetMs,
		paused
	}: {
		src: string;
		offsetMs: number;
		startOffsetMs: number;
		endOffsetMs: number;
		paused: boolean;
	} = $props();

	let video: HTMLVideoElement | null = $state(null);

	$effect(() => {
		if (!video) return;
		const localTimeSeconds = Math.max(
			0,
			Math.min(offsetMs - startOffsetMs, endOffsetMs - startOffsetMs) / 1000
		);
		if (Math.abs(video.currentTime - localTimeSeconds) > 0.3) {
			video.currentTime = localTimeSeconds;
		}
		if (paused || offsetMs < startOffsetMs || offsetMs >= endOffsetMs) {
			video.pause();
		} else {
			void video.play().catch(() => {});
		}
	});
</script>

<video bind:this={video} {src} muted playsinline preload="auto" class="h-full w-full object-contain"
></video>
