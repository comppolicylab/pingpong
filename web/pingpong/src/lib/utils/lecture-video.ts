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

export function getKnowledgeCheckVisualOffsetMs(
	currentTimeMs: number,
	questionStopOffsetMs: number,
	hasVisibleQuestionPrompt: boolean
): number | null {
	if (!hasVisibleQuestionPrompt || currentTimeMs < questionStopOffsetMs) return null;
	return Math.max(0, questionStopOffsetMs - 1);
}
