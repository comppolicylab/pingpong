export type AudioPlaylistSegment = {
	src: string;
	startOffsetMs: number;
	endOffsetMs: number;
	durationMs: number;
};

const SEGMENT_END_TOLERANCE_MS = 50;

export function isCompleteAudioPlaylist(
	segments: AudioPlaylistSegment[],
	durationMs: number
): boolean {
	return (
		segments.length > 0 &&
		segments[0].startOffsetMs === 0 &&
		segments.every(
			(segment, index) =>
				segment.endOffsetMs > segment.startOffsetMs &&
				segment.endOffsetMs - segment.startOffsetMs === segment.durationMs &&
				(index === 0 || segment.startOffsetMs === segments[index - 1].endOffsetMs)
		) &&
		segments[segments.length - 1].endOffsetMs === durationMs
	);
}

export function isAudioPlaylistSegmentEndPause(
	currentTimeMs: number,
	durationMs: number,
	ended: boolean
): boolean {
	return ended || (durationMs > 0 && currentTimeMs >= durationMs - SEGMENT_END_TOLERANCE_MS);
}

export function shouldForwardDeferredAudioPlaylistPause(
	shouldStopAtBoundary: boolean,
	hasNextSegment: boolean
): boolean {
	return shouldStopAtBoundary || !hasNextSegment;
}

export function audioPlaylistSegmentIndexAtOffset(
	segments: AudioPlaylistSegment[],
	offsetMs: number
): number {
	if (segments.length === 0) return -1;
	const boundedOffsetMs = Math.max(
		0,
		Math.min(offsetMs, segments[segments.length - 1].endOffsetMs)
	);
	const segmentIndex = segments.findIndex(
		(segment) => boundedOffsetMs >= segment.startOffsetMs && boundedOffsetMs < segment.endOffsetMs
	);
	return segmentIndex >= 0 ? segmentIndex : segments.length - 1;
}
