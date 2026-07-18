import { describe, expect, it } from 'vitest';

import { clampedGifTimeMs, gifFrameIndexAtTime } from './lecture-slide-gif';

describe('clampedGifTimeMs', () => {
	it('maps lecture offsets within the GIF to their elapsed time', () => {
		expect(clampedGifTimeMs(55_120, 52_650, 4_940)).toBe(2_470);
	});

	it('starts at the first frame before and at the GIF start', () => {
		expect(clampedGifTimeMs(52_649, 52_650, 4_940)).toBe(0);
		expect(clampedGifTimeMs(52_650, 52_650, 4_940)).toBe(0);
	});

	it('holds at the end after the GIF has played once', () => {
		expect(clampedGifTimeMs(57_590, 52_650, 4_940)).toBe(4_940);
		expect(clampedGifTimeMs(65_000, 52_650, 4_940)).toBe(4_940);
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
