<script lang="ts">
	import LectureVideoQuestionCard from './LectureVideoQuestionCard.svelte';

	type SidebarQuestion = { id: number; position: number; questionText: string };
	type QuestionOption = { id: number; option_text: string; post_answer_text?: string | null };
	type CurrentQuestion = {
		id: number;
		type: string;
		question_text: string;
		intro_text: string;
		stop_offset_ms: number;
		intro_narration_id: number | null;
		options: QuestionOption[];
	};
	type CurrentContinuation = {
		option_id: number;
		correct_option_id: number | null;
		post_answer_text: string | null;
		post_answer_narration_id: number | null;
		resume_offset_ms: number;
		next_question: object | null;
		complete: boolean;
	};
	type AnsweredQuestion = {
		selectedOptionId: number;
		correctOptionId: number | null;
		options: QuestionOption[];
	};

	let {
		allQuestions = [],
		currentQuestionId = null,
		currentQuestion = null,
		currentContinuation = null,
		sessionState = 'playing',
		answeredQuestions = new Map(),
		answeringDisabled = false,
		continueDisabled = false,
		scrollToQuestionId = null,
		active = true,
		onselectOption,
		oncontinue,
		onscrollcomplete
	}: {
		allQuestions: SidebarQuestion[];
		currentQuestionId: number | null;
		currentQuestion: CurrentQuestion | null;
		currentContinuation: CurrentContinuation | null;
		sessionState: 'playing' | 'awaiting_answer' | 'awaiting_post_answer_resume' | 'completed';
		answeredQuestions: Map<number, AnsweredQuestion>;
		answeringDisabled?: boolean;
		continueDisabled?: boolean;
		scrollToQuestionId: number | null;
		active?: boolean;
		onselectOption: (optionId: number) => void;
		oncontinue: () => void;
		onscrollcomplete: () => void;
	} = $props();

	let expandedAnsweredId: number | null = $state(null);
	let isAwaitingAnswer = $derived(sessionState === 'awaiting_answer');
	let isAwaitingPostAnswerResume = $derived(sessionState === 'awaiting_post_answer_resume');
	const noop = () => {};

	function questionCardId(questionId: number): string {
		return `question-card-${questionId}`;
	}

	function isVisibleQuestion(questionId: number): boolean {
		return (
			answeredQuestions.has(questionId) ||
			(questionId === currentQuestionId && (isAwaitingAnswer || isAwaitingPostAnswerResume))
		);
	}

	function toggleExpandedAnswered(questionId: number) {
		expandedAnsweredId = expandedAnsweredId === questionId ? null : questionId;
	}

	let sortedQuestions = $derived(
		[...allQuestions]
			.filter(({ id }) => isVisibleQuestion(id))
			.sort((a, b) => a.position - b.position)
	);

	$effect(() => {
		if (!active) return;
		if (scrollToQuestionId == null) return;
		expandedAnsweredId = scrollToQuestionId;
		const el = document.getElementById(questionCardId(scrollToQuestionId));
		if (el) {
			el.scrollIntoView({ behavior: 'smooth', block: 'center' });
			onscrollcomplete();
		}
	});
</script>

<div class="flex max-h-[calc(100dvh-3rem)] flex-col gap-4 border-s border-slate-200 ps-6">
	<div>
		<h2 class="text-base font-semibold text-slate-950">Comprehension Checks</h2>
	</div>

	<div class="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1">
		{#each sortedQuestions as question (question.id)}
			{@const answered = answeredQuestions.get(question.id)}
			{@const isCurrentAnswering = question.id === currentQuestionId && isAwaitingAnswer}
			{@const isCurrentFeedback = question.id === currentQuestionId && isAwaitingPostAnswerResume}
			<div id={questionCardId(question.id)}>
				{#if answered && !isCurrentFeedback}
					<LectureVideoQuestionCard
						position={question.position}
						questionText={question.questionText}
						options={answered.options}
						state="answered"
						selectedOptionId={answered.selectedOptionId}
						correctOptionId={answered.correctOptionId}
						postAnswerText={null}
						expanded={expandedAnsweredId === question.id}
						ontoggleExpand={() => toggleExpandedAnswered(question.id)}
						onselectOption={noop}
					/>
				{:else if isCurrentAnswering && currentQuestion}
					<LectureVideoQuestionCard
						position={question.position}
						questionText={question.questionText}
						options={currentQuestion.options}
						state="answering"
						selectedOptionId={null}
						correctOptionId={null}
						postAnswerText={null}
						expanded={false}
						{answeringDisabled}
						{onselectOption}
						ontoggleExpand={noop}
					/>
				{:else if isCurrentFeedback && currentQuestion && currentContinuation}
					<LectureVideoQuestionCard
						position={question.position}
						questionText={question.questionText}
						options={currentQuestion.options}
						state="feedback"
						selectedOptionId={currentContinuation.option_id}
						correctOptionId={currentContinuation.correct_option_id}
						postAnswerText={currentContinuation.post_answer_text}
						expanded={false}
						showContinue={true}
						{continueDisabled}
						{oncontinue}
						onselectOption={noop}
						ontoggleExpand={noop}
					/>
				{/if}
			</div>
		{/each}
	</div>
</div>
