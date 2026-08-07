import { describe, expect, it } from 'vitest';
import {
	audioPlaylistSegmentIndexAtOffset,
	isAudioPlaylistSegmentEndPause,
	isCompleteAudioPlaylist,
	shouldForwardDeferredAudioPlaylistPause,
	type AudioPlaylistSegment
} from './audio-playlist';

const segments: AudioPlaylistSegment[] = [
	{ src: '/one.ogg', startOffsetMs: 0, endOffsetMs: 1_000, durationMs: 1_000 },
	{ src: '/two.ogg', startOffsetMs: 1_000, endOffsetMs: 2_500, durationMs: 1_500 }
];

describe('audio playlist timeline', () => {
	it('selects the next clip at an exact slide boundary', () => {
		expect(audioPlaylistSegmentIndexAtOffset(segments, 999)).toBe(0);
		expect(audioPlaylistSegmentIndexAtOffset(segments, 1_000)).toBe(1);
	});

	it('keeps the final offset on the final clip', () => {
		expect(audioPlaylistSegmentIndexAtOffset(segments, 2_500)).toBe(1);
	});

	it('requires a contiguous playlist that covers the logical duration', () => {
		expect(isCompleteAudioPlaylist(segments, 2_500)).toBe(true);
		expect(
			isCompleteAudioPlaylist([segments[0], { ...segments[1], startOffsetMs: 1_100 }], 2_500)
		).toBe(false);
		expect(isCompleteAudioPlaylist(segments, 3_000)).toBe(false);
		expect(isCompleteAudioPlaylist([{ ...segments[0], durationMs: 900 }, segments[1]], 2_500)).toBe(
			false
		);
	});

	it('recognizes the native pause immediately before a segment-ended event', () => {
		expect(isAudioPlaylistSegmentEndPause(999, 1_000, false)).toBe(true);
		expect(isAudioPlaylistSegmentEndPause(500, 1_000, false)).toBe(false);
		expect(isAudioPlaylistSegmentEndPause(500, 1_000, true)).toBe(true);
	});

	it('does not forward pause while auto-continuing into the second segment', () => {
		expect(shouldForwardDeferredAudioPlaylistPause(false, true)).toBe(false);
		expect(shouldForwardDeferredAudioPlaylistPause(true, true)).toBe(true);
		expect(shouldForwardDeferredAudioPlaylistPause(false, false)).toBe(true);
	});
});
