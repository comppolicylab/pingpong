import type {
	LectureSlideContentKind,
	LectureSlideQuestionDraftMode,
	LectureSlideQuestionType
} from './api';
import { lecturePronunciationError } from './lecturePronunciation';

export type LectureSlideContentJsonOption = {
	option_text: string;
	correct: boolean;
	post_answer_text: string;
};

export type LectureSlideContentJsonQuestion = {
	type: LectureSlideQuestionType;
	mode: LectureSlideQuestionDraftMode;
	intro_text: string;
	question_text: string;
	options: LectureSlideContentJsonOption[];
};

export type LectureSlideContentJsonSlide = {
	slide_number: number;
	content_kind: LectureSlideContentKind;
	source_context: {
		slide_title: string | null;
		extracted_slide_text: string | null;
		image_description: string | null;
	};
	user_notes: string;
	narration_text: string | null;
	questions: LectureSlideContentJsonQuestion[];
};

export type LectureSlideContentJson = {
	version: 1;
	slides: LectureSlideContentJsonSlide[];
};

export type LectureSlideContentPageDraft = {
	position: number;
	content_kind: LectureSlideContentKind;
	title?: string | null;
	extracted_text?: string | null;
	image_description?: string | null;
	user_notes?: string | null;
	narration_text?: string | null;
};

export type LectureSlideContentQuestionOptionDraft = {
	id?: number | null;
	client_id: string;
	option_text: string;
	post_answer_text: string;
	correct: boolean;
};

export type LectureSlideContentQuestionDraft = {
	id?: number | null;
	client_id: string;
	mode: LectureSlideQuestionDraftMode;
	slide_position: number;
	question_text: string;
	intro_text: string;
	options: LectureSlideContentQuestionOptionDraft[];
};

export const buildLectureSlideContentJson = (
	pages: LectureSlideContentPageDraft[],
	questions: LectureSlideContentQuestionDraft[]
): LectureSlideContentJson => ({
	version: 1,
	slides: [...pages]
		.sort((left, right) => left.position - right.position)
		.map((page) => ({
			slide_number: page.position + 1,
			content_kind: page.content_kind,
			source_context: {
				slide_title: page.title || null,
				extracted_slide_text: page.extracted_text || null,
				image_description: page.image_description || null
			},
			user_notes: page.user_notes || '',
			narration_text: page.content_kind === 'video' ? null : page.narration_text || '',
			questions: questions
				.filter((question) => question.slide_position === page.position)
				.map((question) => ({
					type: 'single_select',
					mode: question.mode,
					intro_text: question.intro_text || '',
					question_text: question.question_text || '',
					options: question.options.map((option) => ({
						option_text: option.option_text || '',
						correct: option.correct,
						post_answer_text: option.post_answer_text || ''
					}))
				}))
		}))
});

const isJsonRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === 'object' && value !== null && !Array.isArray(value);

const isQuestionMode = (value: unknown): value is LectureSlideQuestionDraftMode =>
	value === 'complete' || value === 'partial' || value === 'marker';

export const parseLectureSlideContentJson = (
	raw: string,
	pages: LectureSlideContentPageDraft[]
): { content: LectureSlideContentJson | null; error: string | null } => {
	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return { content: null, error: 'Lecture slide content must be valid JSON.' };
	}
	if (!isJsonRecord(parsed) || parsed.version !== 1 || !Array.isArray(parsed.slides)) {
		return {
			content: null,
			error: 'Lecture slide content must be a Version 1 object with a slides array.'
		};
	}
	if (parsed.slides.length !== pages.length) {
		return {
			content: null,
			error: `Lecture slide content must include exactly ${pages.length} slides.`
		};
	}

	const slides: LectureSlideContentJsonSlide[] = [];
	const seenSlideNumbers = new Set<number>();
	for (const rawSlide of parsed.slides) {
		if (!isJsonRecord(rawSlide)) {
			return { content: null, error: 'Each lecture slide must be a JSON object.' };
		}
		const slideNumber = rawSlide.slide_number;
		if (
			typeof slideNumber !== 'number' ||
			!Number.isInteger(slideNumber) ||
			slideNumber < 1 ||
			slideNumber > pages.length ||
			seenSlideNumbers.has(slideNumber)
		) {
			return {
				content: null,
				error: 'Each slide_number must be unique and match an existing slide.'
			};
		}
		if (typeof rawSlide.narration_text === 'string') {
			const pronunciationError = lecturePronunciationError(rawSlide.narration_text);
			if (pronunciationError) {
				return {
					content: null,
					error: `Slide ${slideNumber} narration: ${pronunciationError}`
				};
			}
		}
		seenSlideNumbers.add(slideNumber);
		const existingPage = pages.find((page) => page.position === slideNumber - 1);
		if (!existingPage || rawSlide.content_kind !== existingPage.content_kind) {
			return {
				content: null,
				error: `Slide ${slideNumber} must keep its existing content_kind.`
			};
		}
		if (
			typeof rawSlide.user_notes !== 'string' ||
			!(typeof rawSlide.narration_text === 'string' || rawSlide.narration_text === null) ||
			!Array.isArray(rawSlide.questions)
		) {
			return {
				content: null,
				error: `Slide ${slideNumber} must include user_notes, narration_text, and questions.`
			};
		}
		if (
			existingPage.content_kind === 'video' &&
			typeof rawSlide.narration_text === 'string' &&
			rawSlide.narration_text.trim()
		) {
			return {
				content: null,
				error: `Slide ${slideNumber} is a video and cannot have generated narration.`
			};
		}

		const questions: LectureSlideContentJsonQuestion[] = [];
		for (const rawQuestion of rawSlide.questions) {
			if (
				!isJsonRecord(rawQuestion) ||
				rawQuestion.type !== 'single_select' ||
				!isQuestionMode(rawQuestion.mode) ||
				typeof rawQuestion.intro_text !== 'string' ||
				typeof rawQuestion.question_text !== 'string' ||
				!Array.isArray(rawQuestion.options)
			) {
				return {
					content: null,
					error: `Every question on slide ${slideNumber} must include a valid type, mode, text, and options.`
				};
			}
			const options: LectureSlideContentJsonOption[] = [];
			const introPronunciationError = lecturePronunciationError(rawQuestion.intro_text);
			if (introPronunciationError) {
				return {
					content: null,
					error: `Question intro on slide ${slideNumber}: ${introPronunciationError}`
				};
			}
			for (const rawOption of rawQuestion.options) {
				if (
					!isJsonRecord(rawOption) ||
					typeof rawOption.option_text !== 'string' ||
					typeof rawOption.correct !== 'boolean' ||
					typeof rawOption.post_answer_text !== 'string'
				) {
					return {
						content: null,
						error: `Every answer option on slide ${slideNumber} must include option_text, correct, and post_answer_text.`
					};
				}
				const feedbackPronunciationError = lecturePronunciationError(rawOption.post_answer_text);
				if (feedbackPronunciationError) {
					return {
						content: null,
						error: `Answer feedback on slide ${slideNumber}: ${feedbackPronunciationError}`
					};
				}
				options.push({
					option_text: rawOption.option_text,
					correct: rawOption.correct,
					post_answer_text: rawOption.post_answer_text
				});
			}
			questions.push({
				type: 'single_select',
				mode: rawQuestion.mode,
				intro_text: rawQuestion.intro_text,
				question_text: rawQuestion.question_text,
				options
			});
		}
		slides.push({
			slide_number: slideNumber,
			content_kind: existingPage.content_kind,
			source_context: {
				slide_title: existingPage.title || null,
				extracted_slide_text: existingPage.extracted_text || null,
				image_description: existingPage.image_description || null
			},
			user_notes: rawSlide.user_notes,
			narration_text: rawSlide.narration_text,
			questions
		});
	}
	slides.sort((left, right) => left.slide_number - right.slide_number);
	return { content: { version: 1, slides }, error: null };
};

const takeMatch = <T>(items: T[], predicate: (item: T) => boolean): T | undefined => {
	const index = items.findIndex(predicate);
	return index < 0 ? undefined : items.splice(index, 1)[0];
};

const questionIdentity = (question: {
	mode: LectureSlideQuestionDraftMode;
	question_text: string;
	intro_text: string;
}) => JSON.stringify([question.mode, question.question_text, question.intro_text]);

const optionIdentity = (option: {
	option_text: string;
	post_answer_text: string;
	correct: boolean;
}) => JSON.stringify([option.option_text, option.post_answer_text, option.correct]);

export const applyLectureSlideContentJson = <Page extends LectureSlideContentPageDraft>(
	content: LectureSlideContentJson,
	pages: Page[],
	existingQuestions: LectureSlideContentQuestionDraft[],
	nextClientId: () => string
): { pages: Page[]; questions: LectureSlideContentQuestionDraft[] } => {
	const slidesByPosition = new Map(content.slides.map((slide) => [slide.slide_number - 1, slide]));
	const existingQuestionsBySlide = new Map<number, LectureSlideContentQuestionDraft[]>();
	for (const question of existingQuestions) {
		const questions = existingQuestionsBySlide.get(question.slide_position) || [];
		questions.push(question);
		existingQuestionsBySlide.set(question.slide_position, questions);
	}

	const updatedPages = pages.map((page) => {
		const slide = slidesByPosition.get(page.position);
		return slide
			? {
					...page,
					user_notes: slide.user_notes,
					narration_text: page.content_kind === 'video' ? '' : slide.narration_text || ''
				}
			: page;
	});
	const updatedQuestions = content.slides.flatMap((slide) => {
		const slidePosition = slide.slide_number - 1;
		const questionsAtSlide = existingQuestionsBySlide.get(slidePosition) || [];
		const unmatchedQuestions = [...questionsAtSlide];
		return slide.questions.map((question, questionIndex) => {
			const existingQuestion =
				takeMatch(
					unmatchedQuestions,
					(candidate) => questionIdentity(candidate) === questionIdentity(question)
				) ||
				takeMatch(unmatchedQuestions, (candidate) => candidate === questionsAtSlide[questionIndex]);
			const unmatchedOptions = [...(existingQuestion?.options || [])];
			return {
				id: existingQuestion?.id,
				client_id: existingQuestion?.client_id || nextClientId(),
				mode: question.mode,
				slide_position: slidePosition,
				question_text: question.question_text,
				intro_text: question.intro_text,
				options: question.options.map((option, optionIndex) => {
					const existingOption =
						takeMatch(
							unmatchedOptions,
							(candidate) => optionIdentity(candidate) === optionIdentity(option)
						) ||
						takeMatch(
							unmatchedOptions,
							(candidate) => candidate === existingQuestion?.options[optionIndex]
						);
					return {
						id: existingOption?.id,
						client_id: existingOption?.client_id || nextClientId(),
						option_text: option.option_text,
						post_answer_text: option.post_answer_text,
						correct: option.correct
					};
				})
			};
		});
	});
	return { pages: updatedPages, questions: updatedQuestions };
};
