import { decompressFrames, parseGIF, type ParsedFrame } from 'gifuct-js';

export type DecodedLectureSlideGif = {
	frames: ParsedFrame[];
	frameEndTimesMs: number[];
	durationMs: number;
	width: number;
	height: number;
};

const decodedGifPromises = new Map<string, Promise<DecodedLectureSlideGif>>();
const MAX_CACHED_GIFS = 3;

function trimDecodedGifCache(): void {
	while (decodedGifPromises.size > MAX_CACHED_GIFS) {
		const oldestSrc = decodedGifPromises.keys().next().value;
		if (oldestSrc === undefined) return;
		decodedGifPromises.delete(oldestSrc);
	}
}

async function decodeLectureSlideGif(src: string): Promise<DecodedLectureSlideGif> {
	const response = await fetch(src);
	if (!response.ok) throw new Error(`GIF request failed with ${response.status}`);
	const parsedGif = parseGIF(await response.arrayBuffer());
	const frames = decompressFrames(parsedGif, true);
	if (frames.length === 0) throw new Error('GIF contains no frames');

	let durationMs = 0;
	const frameEndTimesMs = frames.map((frame) => {
		durationMs += Number.isFinite(frame.delay) && frame.delay > 0 ? frame.delay : 100;
		return durationMs;
	});
	return {
		frames,
		frameEndTimesMs,
		durationMs,
		width: parsedGif.lsd.width,
		height: parsedGif.lsd.height
	};
}

export function loadLectureSlideGif(src: string): Promise<DecodedLectureSlideGif> {
	const cached = decodedGifPromises.get(src);
	if (cached) {
		decodedGifPromises.delete(src);
		decodedGifPromises.set(src, cached);
		return cached;
	}

	const pending = decodeLectureSlideGif(src);
	decodedGifPromises.set(src, pending);
	void pending.catch(() => {
		if (decodedGifPromises.get(src) === pending) {
			decodedGifPromises.delete(src);
		}
	});
	trimDecodedGifCache();
	return pending;
}

export function preloadLectureSlideGif(src: string): void {
	if (typeof window === 'undefined') return;
	void loadLectureSlideGif(src).catch((error) => {
		console.error('Could not preload lecture slide GIF', error);
	});
}

export function clampedGifTimeMs(
	offsetMs: number,
	startOffsetMs: number,
	durationMs: number
): number {
	if (durationMs <= 0) return 0;
	const elapsedMs = Math.max(0, offsetMs - startOffsetMs);
	return Math.min(elapsedMs, durationMs);
}

export function gifFrameIndexAtTime(frameEndTimesMs: number[], timeMs: number): number {
	if (frameEndTimesMs.length === 0) return -1;
	let lowerBound = 0;
	let upperBound = frameEndTimesMs.length - 1;
	while (lowerBound < upperBound) {
		const midpoint = Math.floor((lowerBound + upperBound) / 2);
		if (timeMs < frameEndTimesMs[midpoint]) {
			upperBound = midpoint;
		} else {
			lowerBound = midpoint + 1;
		}
	}
	return lowerBound;
}
