import { describe, expect, it } from 'vitest';

import { gifFrameIndexAtTime, loopedGifTimeMs } from './lecture-slide-gif';

describe('loopedGifTimeMs', () => {
	it('maps the same lecture offset to the same point in the GIF loop', () => {
		expect(loopedGifTimeMs(65_000, 52_650, 4_940)).toBe(2_470);
		expect(loopedGifTimeMs(65_000, 52_650, 4_940)).toBe(2_470);
	});

	it('starts at the first frame before and at the GIF start', () => {
		expect(loopedGifTimeMs(52_649, 52_650, 4_940)).toBe(0);
		expect(loopedGifTimeMs(52_650, 52_650, 4_940)).toBe(0);
	});
});

describe('gifFrameIndexAtTime', () => {
	it('uses frame end times as exclusive boundaries', () => {
		const frameEndTimesMs = [100, 250, 500];
		expect(gifFrameIndexAtTime(frameEndTimesMs, 0)).toBe(0);
		expect(gifFrameIndexAtTime(frameEndTimesMs, 99)).toBe(0);
		expect(gifFrameIndexAtTime(frameEndTimesMs, 100)).toBe(1);
		expect(gifFrameIndexAtTime(frameEndTimesMs, 499)).toBe(2);
	});
});
