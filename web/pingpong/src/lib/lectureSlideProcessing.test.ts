import { describe, expect, it } from 'vitest';

import { deriveLectureSlideProcessingTriggers } from './lectureSlideProcessing';

const triggers = (
	overrides: Partial<Parameters<typeof deriveLectureSlideProcessingTriggers>[0]> = {}
) =>
	deriveLectureSlideProcessingTriggers({
		isLectureSlideMode: true,
		isCreating: false,
		deckIdChanged: false,
		structureChanged: false,
		narrationPromptChanged: false,
		additionalContextFilesChanged: false,
		notesChanged: false,
		narrationChanged: false,
		generationPromptChanged: false,
		questionDraftsRequireGeneration: false,
		voiceChanged: false,
		completeQuestionsChanged: false,
		...overrides
	});

describe('deriveLectureSlideProcessingTriggers', () => {
	it('regenerates narration for note-only edits', () => {
		expect(triggers({ notesChanged: true })).toEqual({
			full: false,
			narration: true,
			questions: false,
			audio: false
		});
	});

	it('regenerates audio instead when replacement narration is provided', () => {
		expect(triggers({ notesChanged: true, narrationChanged: true })).toEqual({
			full: false,
			narration: false,
			questions: false,
			audio: true
		});
	});

	it('regenerates questions for partial or marker drafts', () => {
		expect(triggers({ questionDraftsRequireGeneration: true }).questions).toBe(true);
	});

	it('regenerates only audio for complete question edits', () => {
		expect(triggers({ completeQuestionsChanged: true })).toEqual({
			full: false,
			narration: false,
			questions: false,
			audio: true
		});
	});

	it('disables update triggers while creating an assistant', () => {
		expect(
			triggers({
				isCreating: true,
				deckIdChanged: true,
				structureChanged: true,
				narrationChanged: true,
				questionDraftsRequireGeneration: true
			})
		).toEqual({
			full: false,
			narration: false,
			questions: false,
			audio: false
		});
	});
});
