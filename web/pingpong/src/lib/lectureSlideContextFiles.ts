import {
	LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER,
	LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
	LECTURE_SLIDE_CONTEXT_FILE_USAGE_FAITHFUL,
	LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
	type LectureSlideAdditionalContextFileMetadata,
	type LectureSlideAdditionalContextFileSummary
} from '$lib/api';

export const isTranscriptFilename = (filename: string): boolean =>
	filename.toLowerCase().includes('transcript');

/**
 * Files are tagged from their name alone on upload; the instructor corrects the
 * guess in the file row, and nothing is persisted until the assistant is saved.
 */
export const defaultLectureSlideContextFileMetadata = (
	filename: string
): LectureSlideAdditionalContextFileMetadata => ({
	file_kind: isTranscriptFilename(filename)
		? LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT
		: LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER,
	usage_mode: LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
	usage_note: ''
});

export const LECTURE_SLIDE_CONTEXT_FILE_KIND_OPTIONS: { value: string; label: string }[] = [
	{ value: LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT, label: 'Transcript' },
	{ value: LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER, label: 'Other' }
];

export const LECTURE_SLIDE_CONTEXT_FILE_USAGE_OPTIONS: { value: string; name: string }[] = [
	{ value: LECTURE_SLIDE_CONTEXT_FILE_USAGE_FAITHFUL, name: 'Follow closely' },
	{ value: LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE, name: 'General guide' }
];

export const usesLectureSlideContextFileUsageMode = (file_kind: string | undefined): boolean =>
	file_kind === LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT;

/**
 * Usage modes only mean something for transcripts, but the picker stays in
 * place (disabled) for other files so rows keep the same shape.
 */
export const lectureSlideContextFileUsageHint = (file_kind: string | undefined): string =>
	usesLectureSlideContextFileUsageMode(file_kind)
		? 'Follow closely keeps narration very close to the transcript. General guide follows its content and pacing, but not its wording.'
		: 'Only transcripts can set how closely narration follows them.';

export const hasLectureSlideContextFileInstructions = (usage_note: string | null | undefined) =>
	Boolean(usage_note?.trim());

export const lectureSlideContextFileInstructionsLabel = (
	usage_note: string | null | undefined
): string =>
	hasLectureSlideContextFileInstructions(usage_note) ? 'Edit instructions' : 'Add instructions';

/**
 * Only the tags the instructor can edit; used to decide whether a save changes
 * anything about the context files, since a retag alone restarts generation.
 */
export const lectureSlideContextFileMetadataSignature = (
	contextFile: LectureSlideAdditionalContextFileSummary
): LectureSlideAdditionalContextFileMetadata & { id: number } => ({
	id: contextFile.id,
	file_kind: contextFile.file_kind,
	usage_mode: contextFile.usage_mode,
	usage_note: contextFile.usage_note?.trim() || ''
});
