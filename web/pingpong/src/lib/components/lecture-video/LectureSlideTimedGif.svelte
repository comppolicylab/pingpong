<script lang="ts">
	import { untrack } from 'svelte';
	import { decompressFrames, parseGIF, type ParsedFrame } from 'gifuct-js';
	import { gifFrameIndexAtTime, loopedGifTimeMs } from '$lib/utils/lecture-slide-gif';

	type DecodedGif = {
		frames: ParsedFrame[];
		frameEndTimesMs: number[];
		durationMs: number;
		width: number;
		height: number;
	};

	let {
		src,
		offsetMs,
		startOffsetMs,
		endOffsetMs,
		timelineMedia,
		paused
	}: {
		src: string;
		offsetMs: number;
		startOffsetMs: number;
		endOffsetMs: number;
		timelineMedia: HTMLMediaElement | null;
		paused: boolean;
	} = $props();

	let canvas: HTMLCanvasElement | null = $state(null);
	let decodedGif: DecodedGif | null = $state(null);
	let loadFailed = $state(false);

	let compositionCanvas: HTMLCanvasElement | null = null;
	let compositionContext: CanvasRenderingContext2D | null = null;
	let patchCanvas: HTMLCanvasElement | null = null;
	let patchContext: CanvasRenderingContext2D | null = null;
	let renderedFrameIndex = -1;
	let renderedLoopIndex = -1;
	let restoreImageData: ImageData | null = null;

	function resetRenderer(gif: DecodedGif) {
		compositionCanvas = document.createElement('canvas');
		compositionCanvas.width = gif.width;
		compositionCanvas.height = gif.height;
		compositionContext = compositionCanvas.getContext('2d');
		patchCanvas = document.createElement('canvas');
		patchContext = patchCanvas.getContext('2d');
		renderedFrameIndex = -1;
		renderedLoopIndex = -1;
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

	function applyPreviousFrameDisposal(gif: DecodedGif) {
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

	function drawNextFrame(gif: DecodedGif, frameIndex: number) {
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

	function renderAtOffset(gif: DecodedGif, displayOffsetMs: number) {
		if (!canvas || !compositionCanvas || !compositionContext) return;
		const elapsedMs = Math.max(0, displayOffsetMs - startOffsetMs);
		const loopIndex = Math.floor(elapsedMs / gif.durationMs);
		const gifTimeMs = loopedGifTimeMs(displayOffsetMs, startOffsetMs, gif.durationMs);
		const targetFrameIndex = gifFrameIndexAtTime(gif.frameEndTimesMs, gifTimeMs);
		if (targetFrameIndex < 0) return;
		if (renderedLoopIndex === loopIndex && renderedFrameIndex === targetFrameIndex) return;

		if (
			renderedLoopIndex !== loopIndex ||
			renderedFrameIndex < 0 ||
			targetFrameIndex < renderedFrameIndex
		) {
			resetComposition();
			renderedLoopIndex = loopIndex;
		}
		for (let frameIndex = renderedFrameIndex + 1; frameIndex <= targetFrameIndex; frameIndex += 1) {
			drawNextFrame(gif, frameIndex);
		}

		const context = canvas.getContext('2d');
		if (!context) return;
		context.clearRect(0, 0, canvas.width, canvas.height);
		context.drawImage(compositionCanvas, 0, 0);
	}

	$effect(() => {
		const requestedSrc = src;
		const abortController = new AbortController();
		decodedGif = null;
		loadFailed = false;
		compositionCanvas = null;
		compositionContext = null;
		patchCanvas = null;
		patchContext = null;
		renderedFrameIndex = -1;
		renderedLoopIndex = -1;
		canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);

		void (async () => {
			try {
				const response = await fetch(requestedSrc, { signal: abortController.signal });
				if (!response.ok) throw new Error(`GIF request failed with ${response.status}`);
				const parsedGif = parseGIF(await response.arrayBuffer());
				const frames = decompressFrames(parsedGif, true);
				if (frames.length === 0) throw new Error('GIF contains no frames');
				let durationMs = 0;
				const frameEndTimesMs = frames.map((frame) => {
					durationMs += Number.isFinite(frame.delay) && frame.delay > 0 ? frame.delay : 100;
					return durationMs;
				});
				if (abortController.signal.aborted) return;
				const gif = {
					frames,
					frameEndTimesMs,
					durationMs,
					width: parsedGif.lsd.width,
					height: parsedGif.lsd.height
				};
				resetRenderer(gif);
				decodedGif = gif;
			} catch (error) {
				if (!abortController.signal.aborted) {
					console.error('Could not decode lecture slide GIF', error);
					loadFailed = true;
				}
			}
		})();

		return () => abortController.abort();
	});

	$effect(() => {
		const gif = decodedGif;
		// While playing, the media element is the timeline source. Avoid restarting
		// this animation loop for every reactive time update from its parent.
		const initialOffsetMs = paused ? offsetMs : untrack(() => offsetMs);
		const targetCanvas = canvas;
		const mediaElement = timelineMedia;
		if (!gif || !targetCanvas) return;

		renderAtOffset(gif, initialOffsetMs);
		if (paused) return;

		const startedAtMs = performance.now();
		let animationFrameId = 0;
		const renderFrame = (nowMs: number) => {
			const timelineOffsetMs = mediaElement
				? mediaElement.currentTime * 1000
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
	<canvas bind:this={canvas} class="h-full w-full object-contain" aria-label="Animated GIF"
	></canvas>
{/if}
