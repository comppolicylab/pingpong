type PostAnswerFeedbackContinuation = {
	correct_option_id: number | null;
	post_answer_text: string | null;
};

export function hasVisiblePostAnswerFeedback<T extends PostAnswerFeedbackContinuation>(
	continuation: T | null
): boolean {
	return (
		continuation?.correct_option_id != null ||
		(continuation?.post_answer_text?.trim().length ?? 0) > 0
	);
}
