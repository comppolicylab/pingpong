<script lang="ts">
	let {
		src,
		onready = () => {},
		onerror = () => {},
		offsetMs,
		startOffsetMs,
		endOffsetMs,
		timelineMedia,
		paused
	}: {
		src: string;
		onready?: () => void;
		onerror?: () => void;
		offsetMs: number;
		startOffsetMs: number;
		endOffsetMs: number;
		timelineMedia: HTMLMediaElement | null;
		paused: boolean;
	} = $props();

	let video: HTMLVideoElement | null = $state(null);

	let ready = false;

	function checkReady() {
		// A paused/hidden video may not deliver a compositor frame callback.
		// loadeddata/seeked with HAVE_CURRENT_DATA confirms a renderable frame.
		if (!video || ready || video.seeking || video.readyState < 2) return;
		ready = true;
		onready();
	}

	$effect(() => {
		if (!video) return;
		const localTimeSeconds = Math.max(
			0,
			Math.min(offsetMs - startOffsetMs, endOffsetMs - startOffsetMs) / 1000
		);
		if (Math.abs(video.currentTime - localTimeSeconds) > 0.3) {
			video.currentTime = localTimeSeconds;
		}
		video.playbackRate = timelineMedia?.playbackRate ?? 1;
		if (paused || offsetMs < startOffsetMs || offsetMs >= endOffsetMs) {
			video.pause();
		} else {
			void video.play().catch(() => {});
		}
	});
</script>

<video
	onloadeddata={checkReady}
	onseeked={checkReady}
	{onerror}
	bind:this={video}
	{src}
	muted
	playsinline
	preload="auto"
	class="h-full w-full object-contain"
></video>
