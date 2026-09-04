<script lang="ts">
	import { untrack } from 'svelte';
	import {
		clampedGifTimeMs,
		gifFrameIndexAtTime,
		loadLectureSlideGif,
		type DecodedLectureSlideGif
	} from '$lib/utils/lecture-slide-gif';

	let {
		src,
		fallbackSrc = null,
		onready = () => {},
		offsetMs,
		startOffsetMs,
		endOffsetMs,
		timelineMedia,
		timelineMediaBaseOffsetMs = 0,
		paused
	}: {
		src: string;
		fallbackSrc?: string | null;
		onready?: () => void;
		offsetMs: number;
		startOffsetMs: number;
		endOffsetMs: number;
		timelineMedia: HTMLMediaElement | null;
		timelineMediaBaseOffsetMs?: number;
		paused: boolean;
	} = $props();

	let canvas: HTMLCanvasElement | null = $state(null);
	let decodedGif: DecodedLectureSlideGif | null = $state(null);
	let loadFailed = $state(false);
	let hasRenderedFrame = $state(false);

	let compositionCanvas: HTMLCanvasElement | null = null;
	let compositionContext: CanvasRenderingContext2D | null = null;
	let patchCanvas: HTMLCanvasElement | null = null;
	let patchContext: CanvasRenderingContext2D | null = null;
	let renderedFrameIndex = -1;
	let restoreImageData: ImageData | null = null;

	function resetRenderer(gif: DecodedLectureSlideGif) {
		compositionCanvas = document.createElement('canvas');
		compositionCanvas.width = gif.width;
		compositionCanvas.height = gif.height;
		compositionContext = compositionCanvas.getContext('2d');
		patchCanvas = document.createElement('canvas');
		patchContext = patchCanvas.getContext('2d');
		renderedFrameIndex = -1;
		restoreImageData = null;

		if (canvas) {
			canvas.width = gif.width;
			canvas.height = gif.height;
		}
	}

	function resetComposition() {
		if (!compositionCanvas || !compositionContext) return;
		compositionContext.clearRect(0, 0, compositionCanvas.width, compositionCanvas.height);
		renderedFrameIndex = -1;
		restoreImageData = null;
	}

	function applyPreviousFrameDisposal(gif: DecodedLectureSlideGif) {
		if (!compositionContext || renderedFrameIndex < 0) return;
		const previousFrame = gif.frames[renderedFrameIndex];
		if (previousFrame.disposalType === 2) {
			compositionContext.clearRect(
				previousFrame.dims.left,
				previousFrame.dims.top,
				previousFrame.dims.width,
				previousFrame.dims.height
			);
		} else if (previousFrame.disposalType === 3 && restoreImageData) {
			compositionContext.putImageData(
				restoreImageData,
				previousFrame.dims.left,
				previousFrame.dims.top
			);
		}
		restoreImageData = null;
	}

	function drawNextFrame(gif: DecodedLectureSlideGif, frameIndex: number) {
		if (!compositionContext || !patchCanvas || !patchContext) return;
		applyPreviousFrameDisposal(gif);

		const frame = gif.frames[frameIndex];
		const { dims } = frame;
		if (frame.disposalType === 3) {
			restoreImageData = compositionContext.getImageData(
				dims.left,
				dims.top,
				dims.width,
				dims.height
			);
		}

		if (patchCanvas.width !== dims.width || patchCanvas.height !== dims.height) {
			patchCanvas.width = dims.width;
			patchCanvas.height = dims.height;
		}
		const patchImageData = patchContext.createImageData(dims.width, dims.height);
		patchImageData.data.set(frame.patch);
		patchContext.putImageData(patchImageData, 0, 0);
		compositionContext.drawImage(patchCanvas, dims.left, dims.top);
		renderedFrameIndex = frameIndex;
	}

	function renderAtOffset(gif: DecodedLectureSlideGif, displayOffsetMs: number) {
		if (!canvas || !compositionCanvas || !compositionContext) return;
		const gifTimeMs = clampedGifTimeMs(displayOffsetMs, startOffsetMs, gif.durationMs);
		const targetFrameIndex = gifFrameIndexAtTime(gif.frameEndTimesMs, gifTimeMs);
		if (targetFrameIndex < 0) return;
		if (renderedFrameIndex === targetFrameIndex) return;

		if (renderedFrameIndex < 0 || targetFrameIndex < renderedFrameIndex) {
			resetComposition();
		}
		for (let frameIndex = renderedFrameIndex + 1; frameIndex <= targetFrameIndex; frameIndex += 1) {
			drawNextFrame(gif, frameIndex);
		}

		const context = canvas.getContext('2d');
		if (!context) return;
		context.clearRect(0, 0, canvas.width, canvas.height);
		context.drawImage(compositionCanvas, 0, 0);
		hasRenderedFrame = true;
		onready();
	}

	$effect(() => {
		const requestedSrc = src;
		let cancelled = false;
		decodedGif = null;
		loadFailed = false;
		hasRenderedFrame = false;
		compositionCanvas = null;
		compositionContext = null;
		patchCanvas = null;
		patchContext = null;
		renderedFrameIndex = -1;
		canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);

		void (async () => {
			try {
				const gif = await loadLectureSlideGif(requestedSrc);
				if (cancelled) return;
				resetRenderer(gif);
				decodedGif = gif;
			} catch (error) {
				if (!cancelled) {
					console.error('Could not decode lecture slide GIF', error);
					loadFailed = true;
					onready();
				}
			}
		})();

		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		const gif = decodedGif;
		// While playing, the media element is the timeline source. Avoid restarting
		// this animation loop for every reactive time update from its parent.
		const initialOffsetMs = paused ? offsetMs : untrack(() => offsetMs);
		const targetCanvas = canvas;
		const mediaElement = timelineMedia;
		const mediaBaseOffsetMs = timelineMediaBaseOffsetMs;
		if (!gif || !targetCanvas) return;

		renderAtOffset(gif, initialOffsetMs);
		if (paused) return;

		const startedAtMs = performance.now();
		let animationFrameId = 0;
		const renderFrame = (nowMs: number) => {
			const timelineOffsetMs = mediaElement
				? mediaBaseOffsetMs + mediaElement.currentTime * 1000
				: initialOffsetMs + nowMs - startedAtMs;
			if (timelineOffsetMs >= endOffsetMs) {
				renderAtOffset(gif, Math.max(startOffsetMs, endOffsetMs - 1));
				return;
			}
			renderAtOffset(gif, timelineOffsetMs);
			animationFrameId = requestAnimationFrame(renderFrame);
		};
		animationFrameId = requestAnimationFrame(renderFrame);
		return () => cancelAnimationFrame(animationFrameId);
	});
</script>

{#if loadFailed}
	<div
		class="flex h-full w-full items-center justify-center px-6 text-center text-sm text-slate-300"
	>
		GIF content unavailable
	</div>
{:else}
	<div class="relative h-full w-full">
		{#if fallbackSrc && !hasRenderedFrame}
			<img
				src={fallbackSrc}
				alt=""
				aria-hidden="true"
				class="absolute inset-0 h-full w-full object-contain"
			/>
		{/if}
		<canvas
			bind:this={canvas}
			class={`absolute inset-0 h-full w-full object-contain ${hasRenderedFrame ? '' : 'invisible'}`}
			aria-label="Animated GIF"
		></canvas>
	</div>
{/if}
