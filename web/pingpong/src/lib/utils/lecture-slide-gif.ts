export function loopedGifTimeMs(
	offsetMs: number,
	startOffsetMs: number,
	durationMs: number
): number {
	if (durationMs <= 0) return 0;
	const elapsedMs = Math.max(0, offsetMs - startOffsetMs);
	return elapsedMs % durationMs;
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
