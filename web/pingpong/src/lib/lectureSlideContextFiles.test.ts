import { describe, expect, it } from 'vitest';

import {
	defaultLectureSlideContextFileMetadata,
	defaultUsageModeForKind,
	isLectureSlideContextFileMetadataValid,
	isTranscriptFilename,
	lectureSlideContextFileBadgeLabel
} from './lectureSlideContextFiles';

describe('isTranscriptFilename', () => {
	it('matches "transcript" anywhere in the name, case-insensitively', () => {
		expect(isTranscriptFilename('lecture3-Transcript.txt')).toBe(true);
		expect(isTranscriptFilename('TRANSCRIPT.docx')).toBe(true);
		expect(isTranscriptFilename('syllabus.pdf')).toBe(false);
	});

	it('does not match by extension alone', () => {
		expect(isTranscriptFilename('lecture3.vtt')).toBe(false);
		expect(isTranscriptFilename('lecture3.srt')).toBe(false);
	});
});

describe('defaultLectureSlideContextFileMetadata', () => {
	it('defaults transcripts to the guide usage mode', () => {
		expect(defaultLectureSlideContextFileMetadata('lecture-transcript.txt')).toEqual({
			file_kind: 'transcript',
			usage_mode: 'guide',
			usage_note: ''
		});
	});

	it('defaults other files to the custom usage mode', () => {
		expect(defaultLectureSlideContextFileMetadata('syllabus.pdf')).toEqual({
			file_kind: 'other',
			usage_mode: 'custom',
			usage_note: ''
		});
	});
});

describe('defaultUsageModeForKind', () => {
	it('resets the usage mode when the kind changes', () => {
		expect(defaultUsageModeForKind('transcript')).toBe('guide');
		expect(defaultUsageModeForKind('other')).toBe('custom');
		expect(defaultUsageModeForKind('summary')).toBe('custom');
	});
});

describe('isLectureSlideContextFileMetadataValid', () => {
	it('requires a note only for transcripts with custom usage', () => {
		expect(
			isLectureSlideContextFileMetadataValid({
				file_kind: 'transcript',
				usage_mode: 'custom',
				usage_note: ''
			})
		).toBe(false);
		expect(
			isLectureSlideContextFileMetadataValid({
				file_kind: 'transcript',
				usage_mode: 'custom',
				usage_note: '   '
			})
		).toBe(false);
		expect(
			isLectureSlideContextFileMetadataValid({
				file_kind: 'transcript',
				usage_mode: 'custom',
				usage_note: 'Only use the summary slides.'
			})
		).toBe(true);
	});

	it('never requires a note for other kinds or usage modes', () => {
		expect(
			isLectureSlideContextFileMetadataValid({
				file_kind: 'transcript',
				usage_mode: 'faithful',
				usage_note: ''
			})
		).toBe(true);
		expect(
			isLectureSlideContextFileMetadataValid({
				file_kind: 'transcript',
				usage_mode: 'guide'
			})
		).toBe(true);
		expect(
			isLectureSlideContextFileMetadataValid({
				file_kind: 'other',
				usage_mode: 'custom',
				usage_note: ''
			})
		).toBe(true);
	});
});

describe('lectureSlideContextFileBadgeLabel', () => {
	it('labels transcripts with their usage mode', () => {
		expect(lectureSlideContextFileBadgeLabel('transcript', 'faithful')).toBe(
			'Transcript · Faithful'
		);
		expect(lectureSlideContextFileBadgeLabel('transcript', 'guide')).toBe('Transcript · Guide');
		expect(lectureSlideContextFileBadgeLabel('transcript', 'custom')).toBe('Transcript · Custom');
	});

	it('labels non-transcript kinds without a usage mode', () => {
		expect(lectureSlideContextFileBadgeLabel('other', 'custom')).toBe('Other');
		expect(lectureSlideContextFileBadgeLabel('summary', 'custom')).toBe('Summary');
	});

	it('falls back to "other" for rows missing the fields', () => {
		expect(lectureSlideContextFileBadgeLabel(undefined, undefined)).toBe('Other');
		expect(lectureSlideContextFileBadgeLabel('transcript', undefined)).toBe('Transcript · Custom');
	});
});
