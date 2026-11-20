import { describe, expect, it } from 'vitest';

import {
	getLectureSlideDisplayOffsetMs,
	getLectureSlidePageIndexAtOffset,
	getLectureSlideVideoTimeSeconds
} from './lecture-video';

const pages = [
	{ start_offset_ms: 0, end_offset_ms: 1000 },
	{ start_offset_ms: 1000, end_offset_ms: 2000 }
];

describe('getLectureSlidePageIndexAtOffset', () => {
	it('uses half-open page intervals during ordinary playback', () => {
		expect(getLectureSlidePageIndexAtOffset(pages, 2000, 999)).toBe(0);
		expect(getLectureSlidePageIndexAtOffset(pages, 2000, 1000)).toBe(1);
	});

	it('keeps the preceding slide at an active question boundary', () => {
		expect(getLectureSlidePageIndexAtOffset(pages, 2000, 1000, 1000)).toBe(0);
		expect(getLectureSlidePageIndexAtOffset(pages, 2000, 1050, 1000)).toBe(0);
	});

	it('falls back to evenly divided page intervals when offsets are absent', () => {
		expect(getLectureSlidePageIndexAtOffset([{}, {}], 2000, 999)).toBe(0);
		expect(getLectureSlidePageIndexAtOffset([{}, {}], 2000, 1000)).toBe(1);
	});
});

describe('getLectureSlideDisplayOffsetMs', () => {
	it('uses the final in-page instant for a question-owned timed slide', () => {
		expect(getLectureSlideDisplayOffsetMs(pages[0], 1000, 1000)).toBe(999);
		expect(getLectureSlideDisplayOffsetMs(pages[0], 1050, 1000)).toBe(999);
	});

	it('does not clamp ordinary playback or a different page', () => {
		expect(getLectureSlideDisplayOffsetMs(pages[0], 999, 1000)).toBe(999);
		expect(getLectureSlideDisplayOffsetMs(pages[1], 1000, 1000)).toBe(1000);
		expect(getLectureSlideDisplayOffsetMs(pages[0], 1000, null)).toBe(1000);
	});
});

describe('video position on the narration timeline', () => {
	it('holds the final frame while longer narration continues', () => {
		expect(getLectureSlideVideoTimeSeconds(4500, 1000, 7000, 2)).toBe(2);
		expect(getLectureSlideVideoTimeSeconds(7000, 1000, 7000, 2)).toBe(2);
	});

	it('returns to the matching frame when seeking back into the clip', () => {
		expect(getLectureSlideVideoTimeSeconds(2500, 1000, 7000, 2)).toBe(1.5);
	});

	it('clamps positions before and after the slide window', () => {
		expect(getLectureSlideVideoTimeSeconds(500, 1000, 3000, 5)).toBe(0);
		expect(getLectureSlideVideoTimeSeconds(4000, 1000, 3000, 5)).toBe(2);
	});

	it('uses the slide position while video metadata is loading', () => {
		expect(getLectureSlideVideoTimeSeconds(2500, 1000, 7000, Infinity)).toBe(1.5);
	});
});
