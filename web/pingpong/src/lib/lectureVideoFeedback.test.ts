import { describe, expect, it } from 'vitest';

import { hasVisiblePostAnswerFeedback } from './lectureVideoFeedback';

describe('hasVisiblePostAnswerFeedback', () => {
	it('treats correctness-only review as visible feedback', () => {
		expect(
			hasVisiblePostAnswerFeedback({
				option_id: 2,
				correct_option_id: 1,
				post_answer_text: null,
				post_answer_narration_id: null,
				resume_offset_ms: 1200,
				next_question: null,
				complete: false
			})
		).toBe(true);
	});

	it('treats non-empty post-answer text as visible feedback', () => {
		expect(
			hasVisiblePostAnswerFeedback({
				option_id: 2,
				correct_option_id: null,
				post_answer_text: 'Try again',
				post_answer_narration_id: null,
				resume_offset_ms: 1200,
				next_question: null,
				complete: false
			})
		).toBe(true);
	});

	it('ignores blank text when there is no correctness review', () => {
		expect(
			hasVisiblePostAnswerFeedback({
				option_id: 2,
				correct_option_id: null,
				post_answer_text: '   ',
				post_answer_narration_id: null,
				resume_offset_ms: 1200,
				next_question: null,
				complete: false
			})
		).toBe(false);
	});
});
