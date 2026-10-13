/** Caption cues can span part of a sentence; prefer punctuation or a gap in speech. */
export function lectureChatBreakOffset(
	positionMs: number,
	cues: { startTime: number; endTime: number; text?: string }[],
	segmentEnds: number[] = []
): number | null {
	const activeIndex = cues.findIndex(
		(cue) => cue.startTime * 1000 <= positionMs && cue.endTime * 1000 > positionMs
	);
	const candidates = segmentEnds.filter((end) => end > positionMs);
	if (activeIndex >= 0) {
		for (let i = activeIndex; i < cues.length; i++) {
			const cue = cues[i];
			const next = cues[i + 1];
			if (
				/[.!?]["'”’)]*\s*$/.test(cue.text ?? '') ||
				!next ||
				next.startTime - cue.endTime >= 0.3
			) {
				candidates.push(cue.endTime * 1000);
				break;
			}
		}
		if (!candidates.some((end) => end - positionMs <= 15_000)) {
			candidates.push(cues[activeIndex].endTime * 1000);
		}
	}
	return candidates.length ? Math.min(...candidates) : null;
}
