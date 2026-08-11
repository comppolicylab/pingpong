import { describe, expect, it } from 'vitest';

import type { LectureSlideAdditionalContextFileSummary } from './api';
import {
	defaultLectureSlideContextFileMetadata,
	hasLectureSlideContextFileInstructions,
	isTranscriptFilename,
	lectureSlideContextFileInstructionsLabel,
	lectureSlideContextFileMetadataSignature,
	lectureSlideContextFileUsageHint,
	usesLectureSlideContextFileUsageMode
} from './lectureSlideContextFiles';

const contextFile = (
	overrides: Partial<LectureSlideAdditionalContextFileSummary> = {}
): LectureSlideAdditionalContextFileSummary => ({
	id: 1,
	filename: 'lecture-transcript.txt',
	size: 2048,
	content_type: 'text/plain',
	file_object_id: 10,
	file_kind: 'transcript',
	usage_mode: 'guide',
	usage_note: null,
	...overrides
});

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
	it('guesses transcripts from the filename and defaults them to the guide usage mode', () => {
		expect(defaultLectureSlideContextFileMetadata('lecture-transcript.txt')).toEqual({
			file_kind: 'transcript',
			usage_mode: 'guide',
			usage_note: ''
		});
	});

	it('defaults everything else to the other kind, still with a submittable usage mode', () => {
		expect(defaultLectureSlideContextFileMetadata('syllabus.pdf')).toEqual({
			file_kind: 'other',
			usage_mode: 'guide',
			usage_note: ''
		});
	});
});

describe('usesLectureSlideContextFileUsageMode', () => {
	it('is only editable for transcripts', () => {
		expect(usesLectureSlideContextFileUsageMode('transcript')).toBe(true);
		expect(usesLectureSlideContextFileUsageMode('other')).toBe(false);
		expect(usesLectureSlideContextFileUsageMode(undefined)).toBe(false);
	});
});

describe('lectureSlideContextFileUsageHint', () => {
	it('explains the modes for transcripts and why the picker is off otherwise', () => {
		expect(lectureSlideContextFileUsageHint('transcript')).toContain('Follow closely');
		expect(lectureSlideContextFileUsageHint('other')).toContain('Only transcripts');
	});
});

describe('lectureSlideContextFileInstructionsLabel', () => {
	it('offers to add instructions until there are some to edit', () => {
		expect(lectureSlideContextFileInstructionsLabel(null)).toBe('Add instructions');
		expect(lectureSlideContextFileInstructionsLabel('')).toBe('Add instructions');
		expect(lectureSlideContextFileInstructionsLabel('   ')).toBe('Add instructions');
		expect(lectureSlideContextFileInstructionsLabel('Use for terminology only.')).toBe(
			'Edit instructions'
		);
	});

	it('treats whitespace-only instructions as absent', () => {
		expect(hasLectureSlideContextFileInstructions('\n\t ')).toBe(false);
		expect(hasLectureSlideContextFileInstructions('a')).toBe(true);
	});
});

describe('lectureSlideContextFileMetadataSignature', () => {
	it('keeps only the tags an instructor can edit', () => {
		expect(
			lectureSlideContextFileMetadataSignature(
				contextFile({ id: 7, usage_note: '  Use for terminology only.  ' })
			)
		).toEqual({
			id: 7,
			file_kind: 'transcript',
			usage_mode: 'guide',
			usage_note: 'Use for terminology only.'
		});
	});

	it('does not report a change when only untagged fields differ', () => {
		expect(lectureSlideContextFileMetadataSignature(contextFile({ size: 1 }))).toEqual(
			lectureSlideContextFileMetadataSignature(contextFile({ size: 999999 }))
		);
	});

	it('normalizes blank and missing instructions to the same value', () => {
		const missing = lectureSlideContextFileMetadataSignature(contextFile({ usage_note: null }));
		expect(lectureSlideContextFileMetadataSignature(contextFile({ usage_note: '   ' }))).toEqual(
			missing
		);
		expect(missing.usage_note).toBe('');
	});

	it('reports a change when the usage mode is retagged', () => {
		expect(
			lectureSlideContextFileMetadataSignature(contextFile({ usage_mode: 'faithful' }))
		).not.toEqual(lectureSlideContextFileMetadataSignature(contextFile({ usage_mode: 'guide' })));
	});
});
