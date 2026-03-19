import type { LectureVideoContinuation } from '$lib/api';

export function hasVisiblePostAnswerFeedback(
	continuation: LectureVideoContinuation | null
): boolean {
	return (
		continuation?.correct_option_id != null ||
		(continuation?.post_answer_text?.trim().length ?? 0) > 0
	);
}
