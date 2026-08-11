import {
	LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER,
	LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
	LECTURE_SLIDE_CONTEXT_FILE_USAGE_CUSTOM,
	LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
	type LectureSlideAdditionalContextFileMetadata
} from '$lib/api';

export type LectureSlideContextFileEntry = {
	file: File;
	metadata: LectureSlideAdditionalContextFileMetadata;
};

export const isTranscriptFilename = (filename: string): boolean =>
	filename.toLowerCase().includes('transcript');

export const defaultUsageModeForKind = (fileKind: string): string =>
	fileKind === LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT
		? LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE
		: LECTURE_SLIDE_CONTEXT_FILE_USAGE_CUSTOM;

export const defaultLectureSlideContextFileMetadata = (
	filename: string
): LectureSlideAdditionalContextFileMetadata => {
	const file_kind = isTranscriptFilename(filename)
		? LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT
		: LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER;
	return { file_kind, usage_mode: defaultUsageModeForKind(file_kind), usage_note: '' };
};

/**
 * The usage note is required (frontend-only) for transcripts with a custom
 * usage mode; it is optional everywhere else.
 */
export const isLectureSlideContextFileMetadataValid = (
	metadata: LectureSlideAdditionalContextFileMetadata
): boolean =>
	metadata.file_kind !== LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT ||
	metadata.usage_mode !== LECTURE_SLIDE_CONTEXT_FILE_USAGE_CUSTOM ||
	Boolean(metadata.usage_note?.trim());

const capitalize = (value: string): string =>
	value ? value.charAt(0).toUpperCase() + value.slice(1) : value;

export const lectureSlideContextFileBadgeLabel = (
	file_kind: string | undefined,
	usage_mode: string | undefined
): string => {
	const kind = file_kind || LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER;
	if (kind === LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT) {
		return `Transcript · ${capitalize(usage_mode || LECTURE_SLIDE_CONTEXT_FILE_USAGE_CUSTOM)}`;
	}
	return capitalize(kind);
};
