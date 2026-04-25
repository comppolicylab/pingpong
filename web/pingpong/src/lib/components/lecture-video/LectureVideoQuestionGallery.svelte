<script lang="ts">
	import {
		ChevronLeftOutline,
		ChevronRightOutline,
		QuestionCircleOutline
	} from 'flowbite-svelte-icons';
	import LectureVideoQuestionCard from './LectureVideoQuestionCard.svelte';

	type GalleryQuestion = { id: number; position: number; questionText: string };
	type QuestionOption = { id: number; option_text: string; post_answer_text?: string | null };
	type AnsweredQuestion = {
		selectedOptionId: number;
		correctOptionId: number | null;
		options: QuestionOption[];
		postAnswerText: string | null;
	};

	let {
		allQuestions = [],
		currentQuestionId = null,
		currentQuestion = null,
		currentContinuation = null,
		sessionState = 'playing',
		answeredQuestions = new Map(),
		answeringDisabled = false,
		showContinue = false,
		continueDisabled = false,
		scrollToQuestionId = null,
		onselectOption,
		oncontinue,
		onscrollcomplete
	}: {
		allQuestions: GalleryQuestion[];
		currentQuestionId: number | null;
		currentQuestion: {
			id: number;
			type: string;
			question_text: string;
			intro_text: string;
			stop_offset_ms: number;
			intro_narration_id: number | null;
			options: QuestionOption[];
		} | null;
		currentContinuation: {
			option_id: number;
			correct_option_id: number | null;
			post_answer_text: string | null;
			post_answer_narration_id: number | null;
			resume_offset_ms: number;
			next_question: object | null;
			complete: boolean;
		} | null;
		sessionState: 'playing' | 'awaiting_answer' | 'awaiting_post_answer_resume' | 'completed';
		answeredQuestions: Map<number, AnsweredQuestion>;
		answeringDisabled?: boolean;
		showContinue?: boolean;
		continueDisabled?: boolean;
		scrollToQuestionId: number | null;
		onselectOption: (optionId: number) => void;
		oncontinue?: () => void;
		onscrollcomplete: () => void;
	} = $props();

	let requestedActiveIndex: number = $state(0);

	const navigationButtonClass =
		'mt-4 xl:mt-12 inline-flex shrink-0 items-center justify-center rounded-full p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-300 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400';
	const dotBaseClass =
		'size-2.5 rounded-full transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-300';
	let continueCardProps = $derived({ showContinue, continueDisabled, oncontinue });

	let hasCurrentPendingQuestion = $derived(
		sessionState === 'awaiting_answer' || sessionState === 'awaiting_post_answer_resume'
	);
	let sortedQuestions = $derived(
		[...allQuestions]
			.filter((question) => answeredQuestions.has(question.id) || isCurrentQuestion(question.id))
			.sort((a, b) => a.position - b.position)
	);
	let activeIndex = $derived(clampIndex(requestedActiveIndex));
	let activeQuestion = $derived(sortedQuestions[activeIndex] ?? null);
	let activeAnsweredQuestion = $derived(
		activeQuestion ? (answeredQuestions.get(activeQuestion.id) ?? null) : null
	);
	let isCurrentAnswering = $derived(
		activeQuestion?.id === currentQuestionId && sessionState === 'awaiting_answer'
	);
	let isCurrentFeedback = $derived(
		activeQuestion?.id === currentQuestionId && sessionState === 'awaiting_post_answer_resume'
	);
	let atFirstQuestion = $derived(activeIndex === 0);
	let atLastQuestion = $derived(activeIndex >= sortedQuestions.length - 1);

	// Auto-navigate to active question when state changes
	$effect(() => {
		if (hasCurrentPendingQuestion && currentQuestionId != null) {
			const idx = findQuestionIndex(currentQuestionId);
			if (idx !== -1) requestedActiveIndex = idx;
		}
	});

	// Navigate to question from video marker click
	$effect(() => {
		if (scrollToQuestionId == null) return;
		const idx = findQuestionIndex(scrollToQuestionId);
		if (idx !== -1) {
			requestedActiveIndex = idx;
			onscrollcomplete();
		}
	});

	function isCurrentQuestion(questionId: number): boolean {
		return questionId === currentQuestionId && hasCurrentPendingQuestion;
	}

	function findQuestionIndex(questionId: number): number {
		return sortedQuestions.findIndex((question) => question.id === questionId);
	}

	function clampIndex(index: number): number {
		if (sortedQuestions.length === 0) return 0;
		return Math.max(0, Math.min(index, sortedQuestions.length - 1));
	}

	function moveActiveIndex(offset: number) {
		requestedActiveIndex = activeIndex + offset;
	}

	function dotClass(questionId: number, index: number): string {
		const answered = answeredQuestions.get(questionId);
		const isViewed = index === activeIndex;
		const ringClasses = isViewed ? ' ring-2 ring-slate-500 ring-offset-2 ring-offset-white' : '';

		if (isCurrentQuestion(questionId)) {
			return 'bg-blue-500' + ringClasses;
		}

		if (answered) {
			if (answered.correctOptionId == null) {
				return 'bg-slate-400' + ringClasses;
			}
			if (answered.selectedOptionId === answered.correctOptionId) {
				return 'bg-emerald-500' + ringClasses;
			}
			return 'bg-rose-500' + ringClasses;
		}

		return 'bg-slate-200' + ringClasses;
	}
</script>

<div class="flex flex-col gap-4 pt-5 xl:h-full xl:min-h-0 xl:gap-0 xl:pt-0">
	<!-- Gallery area -->
	{#if sortedQuestions.length > 0}
		<div class="flex items-start gap-2 sm:gap-3 xl:min-h-0 xl:flex-1">
			<button
				type="button"
				disabled={atFirstQuestion}
				onclick={() => moveActiveIndex(-1)}
				aria-label="Previous question"
				class={navigationButtonClass}
			>
				<ChevronLeftOutline class="size-5" />
			</button>

			<div
				class="min-w-0 flex-1 xl:-mt-4 xl:min-h-0 xl:self-stretch xl:overflow-y-auto xl:[scrollbar-width:thin]"
			>
				<div class="xl:pt-12">
					{#if activeQuestion}
						{#if activeAnsweredQuestion && !isCurrentFeedback}
							<LectureVideoQuestionCard
								position={activeQuestion.position}
								questionText={activeQuestion.questionText}
								options={activeAnsweredQuestion.options}
								state="answered"
								selectedOptionId={activeAnsweredQuestion.selectedOptionId}
								correctOptionId={activeAnsweredQuestion.correctOptionId}
								postAnswerText={activeAnsweredQuestion.postAnswerText}
								headerTrailing={dots}
							/>
						{:else if isCurrentAnswering && currentQuestion}
							<LectureVideoQuestionCard
								position={activeQuestion.position}
								questionText={activeQuestion.questionText}
								options={currentQuestion.options}
								state="answering"
								selectedOptionId={null}
								correctOptionId={null}
								postAnswerText={null}
								{answeringDisabled}
								{onselectOption}
								headerTrailing={dots}
							/>
						{:else if isCurrentFeedback && currentQuestion && currentContinuation}
							<LectureVideoQuestionCard
								position={activeQuestion.position}
								questionText={activeQuestion.questionText}
								options={currentQuestion.options}
								state="feedback"
								selectedOptionId={currentContinuation.option_id}
								correctOptionId={currentContinuation.correct_option_id}
								postAnswerText={currentContinuation.post_answer_text}
								{...continueCardProps}
								headerTrailing={dots}
							/>
						{/if}
					{/if}
				</div>
			</div>

			<button
				type="button"
				disabled={atLastQuestion}
				onclick={() => moveActiveIndex(1)}
				aria-label="Next question"
				class={navigationButtonClass}
			>
				<ChevronRightOutline class="size-5" />
			</button>
		</div>
	{:else}
		<div class="flex min-h-48 flex-1 items-center justify-center px-4 py-8 xl:min-h-0">
			<div class="flex max-w-sm flex-col items-center text-center">
				<div
					class="mb-3 flex size-12 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-400"
				>
					<QuestionCircleOutline class="size-6" />
				</div>
				<h2 class="text-sm font-semibold text-slate-900">No comprehension checks yet</h2>
				<p class="mt-1 max-w-72 text-sm text-slate-500">
					Comprehension checks will appear here as you reach them in the lecture
				</p>
			</div>
		</div>
	{/if}
</div>

{#snippet dots()}
	{#if sortedQuestions.length > 1}
		<div class="flex shrink-0 items-center gap-1.5 pt-1">
			{#each sortedQuestions as question, index (question.id)}
				<button
					type="button"
					onclick={() => (requestedActiveIndex = index)}
					class="{dotBaseClass} {dotClass(question.id, index)}"
					aria-label="Go to question {question.position}"
				></button>
			{/each}
		</div>
	{/if}
{/snippet}
