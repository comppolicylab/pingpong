export type LectureVideoQuestionOption = {
	id: number;
	option_text: string;
	post_answer_text?: string | null;
};

export function mergeQuestionOptions(
	existingOptions: LectureVideoQuestionOption[],
	incomingOptions: LectureVideoQuestionOption[]
): LectureVideoQuestionOption[] {
	const existingById = new Map(existingOptions.map((option) => [option.id, option]));
	return incomingOptions.map((option) => ({
		...option,
		post_answer_text:
			option.post_answer_text ?? existingById.get(option.id)?.post_answer_text ?? null
	}));
}

export type LectureSlideTimelinePage = {
	start_offset_ms?: number | null;
	end_offset_ms?: number | null;
};

export function getLectureSlidePageIndexAtOffset(
	pages: LectureSlideTimelinePage[],
	durationMs: number,
	offsetMs: number,
	questionBoundaryMs: number | null = null
): number {
	if (pages.length === 0) return -1;

	const current = Math.max(0, Math.min(offsetMs, durationMs));
	const pageBounds = pages.map((page, index) => ({
		start: page.start_offset_ms ?? Math.floor((index * durationMs) / pages.length),
		end: page.end_offset_ms ?? Math.floor(((index + 1) * durationMs) / pages.length)
	}));

	// A visible knowledge check owns the instant at the end of its slide. This
	// keeps the canonical media position at the exact checkpoint while the
	// ordinary playback timeline remains half-open and advances to the next slide.
	if (questionBoundaryMs != null && current >= questionBoundaryMs) {
		const ownerIndex = pageBounds.findIndex(({ end }) => end === questionBoundaryMs);
		if (ownerIndex >= 0) return ownerIndex;
	}

	const pageIndex = pageBounds.findIndex(({ start, end }) => current >= start && current < end);
	return pageIndex >= 0 ? pageIndex : pages.length - 1;
}
