import { describe, expect, it } from 'vitest';

import {
	applyLectureSlideContentJson,
	buildLectureSlideContentJson,
	parseLectureSlideContentJson,
	type LectureSlideContentPageDraft,
	type LectureSlideContentQuestionDraft
} from './lectureSlideContentJson';

const pages: LectureSlideContentPageDraft[] = [
	{
		position: 0,
		content_kind: 'slide',
		title: 'Introduction',
		extracted_text: 'Treatment and control',
		image_description: 'Two groups',
		user_notes: 'Set up the example.',
		narration_text: 'Opening narration.'
	},
	{
		position: 1,
		content_kind: 'slide',
		title: 'Results',
		user_notes: '',
		narration_text: 'Results narration.'
	}
];

const questions: LectureSlideContentQuestionDraft[] = [
	{
		id: 10,
		client_id: 'question-10',
		mode: 'complete',
		slide_position: 0,
		question_text: 'Complete?',
		intro_text: 'Check your understanding.',
		options: [
			{
				id: 100,
				client_id: 'option-100',
				option_text: 'Yes',
				post_answer_text: 'Correct.',
				correct: true
			},
			{
				id: 101,
				client_id: 'option-101',
				option_text: 'No',
				post_answer_text: 'Try again.',
				correct: false
			}
		]
	},
	{
		id: 11,
		client_id: 'question-11',
		mode: 'partial',
		slide_position: 0,
		question_text: 'Looks complete but remains partial?',
		intro_text: '',
		options: [
			{
				id: 110,
				client_id: 'option-110',
				option_text: 'Yes',
				post_answer_text: '',
				correct: true
			},
			{
				id: 111,
				client_id: 'option-111',
				option_text: 'No',
				post_answer_text: '',
				correct: false
			}
		]
	},
	{
		id: 12,
		client_id: 'question-12',
		mode: 'marker',
		slide_position: 1,
		question_text: '',
		intro_text: '',
		options: []
	}
];

describe('lecture slide content JSON', () => {
	it('round trips complete, partial, and marker question modes', () => {
		const document = buildLectureSlideContentJson(pages, questions);
		const parsed = parseLectureSlideContentJson(JSON.stringify(document), pages);

		expect(parsed.error).toBeNull();
		expect(parsed.content).toEqual(document);
		expect(
			parsed.content?.slides.flatMap((slide) => slide.questions.map((question) => question.mode))
		).toEqual(['complete', 'partial', 'marker']);
	});

	it('normalizes slide order and restores authoritative source context', () => {
		const document = buildLectureSlideContentJson(pages, questions);
		document.slides.reverse();
		document.slides[1].source_context.slide_title = 'Ignored edit';

		const parsed = parseLectureSlideContentJson(JSON.stringify(document), pages);

		expect(parsed.error).toBeNull();
		expect(parsed.content?.slides.map((slide) => slide.slide_number)).toEqual([1, 2]);
		expect(parsed.content?.slides[0].source_context.slide_title).toBe('Introduction');
	});

	it('preserves question and option IDs when JSON arrays are reordered', () => {
		const document = buildLectureSlideContentJson(pages, questions);
		document.slides[0].questions.reverse();
		document.slides[0].questions[1].options.reverse();

		const applied = applyLectureSlideContentJson(document, pages, questions, () => 'new-id');

		expect(applied.questions.map((question) => question.id)).toEqual([11, 10, 12]);
		expect(applied.questions[1].options.map((option) => option.id)).toEqual([101, 100]);
	});

	it('does not silently demote an incomplete complete question', () => {
		const document = buildLectureSlideContentJson(pages, questions);
		document.slides[0].questions[0].options.pop();

		const applied = applyLectureSlideContentJson(document, pages, questions, () => 'new-id');

		expect(applied.questions[0].mode).toBe('complete');
		expect(applied.questions[0].options).toHaveLength(1);
	});

	it('preserves pronunciation annotations in every spoken field', () => {
		const document = buildLectureSlideContentJson(pages, questions);
		document.slides[0].narration_text = 'The pipes [[lead=>leed]] water away.';
		document.slides[0].questions[0].intro_text = 'You [[lead=>leed]] this step.';
		document.slides[0].questions[0].options[0].post_answer_text =
			'This will [[lead=>leed]] onward.';

		const parsed = parseLectureSlideContentJson(JSON.stringify(document), pages);

		expect(parsed.error).toBeNull();
		expect(parsed.content).toEqual(document);
	});

	it('rejects malformed pronunciation annotations with field context', () => {
		const document = buildLectureSlideContentJson(pages, questions);
		document.slides[0].questions[0].intro_text = 'Broken [[lead=leed]].';

		const parsed = parseLectureSlideContentJson(JSON.stringify(document), pages);

		expect(parsed.content).toBeNull();
		expect(parsed.error).toContain('Question intro on slide 1');
	});
});
