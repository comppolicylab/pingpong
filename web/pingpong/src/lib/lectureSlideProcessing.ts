export type LectureSlideProcessingTriggers = {
	full: boolean;
	narration: boolean;
	questions: boolean;
	audio: boolean;
};

export const deriveLectureSlideProcessingTriggers = ({
	isLectureSlideMode,
	isCreating,
	modelChanged = false,
	deckIdChanged,
	structureChanged,
	narrationPromptChanged,
	additionalContextFilesChanged,
	notesChanged,
	narrationChanged,
	generationPromptChanged,
	questionDraftsRequireGeneration,
	voiceChanged,
	completeQuestionsChanged
}: {
	isLectureSlideMode: boolean;
	isCreating: boolean;
	modelChanged?: boolean;
	deckIdChanged: boolean;
	structureChanged: boolean;
	narrationPromptChanged: boolean;
	additionalContextFilesChanged: boolean;
	notesChanged: boolean;
	narrationChanged: boolean;
	generationPromptChanged: boolean;
	questionDraftsRequireGeneration: boolean;
	voiceChanged: boolean;
	completeQuestionsChanged: boolean;
}): LectureSlideProcessingTriggers => {
	const enabled = isLectureSlideMode && !isCreating;
	const full = enabled && deckIdChanged;
	// Match the backend: notes regenerate narration only when the same save does
	// not also provide replacement narration text.
	const narration =
		enabled &&
		(full ||
			modelChanged ||
			structureChanged ||
			narrationPromptChanged ||
			additionalContextFilesChanged ||
			(notesChanged && !narrationChanged));
	const questions =
		enabled &&
		(full ||
			modelChanged ||
			structureChanged ||
			generationPromptChanged ||
			additionalContextFilesChanged ||
			questionDraftsRequireGeneration);
	const audio =
		enabled && !narration && (voiceChanged || narrationChanged || completeQuestionsChanged);
	return { full, narration, questions, audio };
};
