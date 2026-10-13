import { describe, expect, it, vi } from 'vitest';
import {
	audioPlaylistSegmentIndexAtOffset,
	playAudioPlaylistSegment,
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

describe('audio playlist resume', () => {
	it('resumes a boundary-paused clip on the next segment without replaying narration', async () => {
		let activeIndex = 0;
		let localOffsetMs = segments[0].durationMs;
		const media = {
			ended: true,
			play: vi.fn(async () => {
				// Native play restarts an ended clip if no new source was selected.
				if (media.ended) localOffsetMs = 0;
			})
		};
		const loadSegment = vi.fn(async (index: number) => {
			expect(media.play).not.toHaveBeenCalled();
			activeIndex = index;
			localOffsetMs = 0;
			media.ended = false;
		});
		await playAudioPlaylistSegment({
			media,
			segments,
			segmentIndex: activeIndex,
			pendingSeek: false,
			loadSegment
		});
		expect(loadSegment).toHaveBeenCalledWith(1);
		expect(media.play).toHaveBeenCalledTimes(1);
		expect(segments[activeIndex].src).toBe('/two.ogg');
		expect(segments[activeIndex].startOffsetMs + localOffsetMs).toBe(1000);
	});

	it('does not advance a mid-segment pause', async () => {
		const media = { ended: false, play: vi.fn().mockResolvedValue(undefined) };
		const loadSegment = vi.fn();
		await playAudioPlaylistSegment({
			media,
			segments,
			segmentIndex: 0,
			pendingSeek: false,
			loadSegment
		});
		expect(loadSegment).not.toHaveBeenCalled();
		expect(media.play).toHaveBeenCalledTimes(1);
	});

	it('honors a queued seek or restart instead of advancing the old ended clip', async () => {
		const media = { ended: true, play: vi.fn().mockResolvedValue(undefined) };
		const loadSegment = vi.fn().mockResolvedValue(undefined);
		await playAudioPlaylistSegment({
			media,
			segments,
			segmentIndex: 0,
			pendingSeek: true,
			loadSegment
		});
		expect(loadSegment).toHaveBeenCalledWith(0);
		expect(media.play).toHaveBeenCalledTimes(1);
	});

	it('does not select a nonexistent segment at the end of the playlist', async () => {
		const media = { ended: true, play: vi.fn().mockResolvedValue(undefined) };
		const loadSegment = vi.fn();
		await playAudioPlaylistSegment({
			media,
			segments,
			segmentIndex: 1,
			pendingSeek: false,
			loadSegment
		});
		expect(loadSegment).not.toHaveBeenCalled();
	});

	it('propagates playback failures so chat continuation can be retried', async () => {
		const media = { ended: true, play: vi.fn().mockRejectedValue(new Error('Playback blocked')) };
		const loadSegment = vi.fn().mockResolvedValue(undefined);
		await expect(
			playAudioPlaylistSegment({
				media,
				segments,
				segmentIndex: 0,
				pendingSeek: false,
				loadSegment
			})
		).rejects.toThrow('Playback blocked');
	});
});
