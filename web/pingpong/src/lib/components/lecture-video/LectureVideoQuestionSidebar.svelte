<script lang="ts">
	import { tick } from 'svelte';

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
		showContinue?: boolean;
		continueDisabled?: boolean;
		scrollToQuestionId: number | null;
		active?: boolean;
		onselectOption: (optionId: number) => void;
		oncontinue?: () => void;
		onscrollcomplete: () => void;
	} = $props();

	let expandedAnsweredId: number | null = $state(null);
	let isPillRailExpanded = $state(false);
	let isPillRailMeasured = $state(false);
	let collapsedVisiblePillIds: number[] = $state([]);
	let hiddenPillCount = $state(0);
	let isAwaitingAnswer = $derived(sessionState === 'awaiting_answer');
	let isAwaitingPostAnswerResume = $derived(sessionState === 'awaiting_post_answer_resume');
	const noop = () => {};
	let continueCardProps = $derived({ showContinue, continueDisabled, oncontinue });
	let pillMeasurementContainer: HTMLDivElement | null = $state(null);

	function questionCardId(questionId: number): string {
		return `question-card-${questionId}`;
	}

	function isVisibleQuestion(questionId: number): boolean {
		return (
			answeredQuestions.has(questionId) ||
			(questionId === currentQuestionId && (isAwaitingAnswer || isAwaitingPostAnswerResume))
		);
	}

	function isCurrentFeedback(questionId: number): boolean {
		return questionId === currentQuestionId && isAwaitingPostAnswerResume;
	}

	function isCurrentAnswering(questionId: number): boolean {
		return questionId === currentQuestionId && isAwaitingAnswer;
	}

	function toggleExpandedAnswered(questionId: number) {
		expandedAnsweredId = expandedAnsweredId === questionId ? null : questionId;
	}

	function togglePillRailExpanded() {
		isPillRailExpanded = !isPillRailExpanded;
	}

	let sortedQuestions = $derived(
		[...allQuestions]
			.filter(({ id }) => isVisibleQuestion(id))
			.sort((a, b) => a.position - b.position)
	);

	let answeredPillQuestions = $derived(
		sortedQuestions.filter((question) => {
			const answered = answeredQuestions.get(question.id);
			return answered && !isCurrentFeedback(question.id);
		})
	);

	let visiblePillQuestions = $derived.by(() => {
		if (isPillRailExpanded) {
			return answeredPillQuestions;
		}

		if (!isPillRailMeasured) {
			return [];
		}

		if (hiddenPillCount === 0) {
			return answeredPillQuestions;
		}

		const visibleIds = new Set(collapsedVisiblePillIds);
		return answeredPillQuestions.filter((question) => visibleIds.has(question.id));
	});

	let fullCardQuestions = $derived(
		sortedQuestions.filter((question) => {
			if (isCurrentAnswering(question.id) || isCurrentFeedback(question.id)) {
				return true;
			}
			return expandedAnsweredId === question.id;
		})
	);

	async function measureCollapsedPillRail() {
		await tick();

		if (!pillMeasurementContainer || answeredPillQuestions.length === 0) {
			collapsedVisiblePillIds = [];
			hiddenPillCount = 0;
			isPillRailMeasured = true;
			isPillRailExpanded = false;
			return;
		}

		const pillNodes = Array.from(
			pillMeasurementContainer.querySelectorAll<HTMLElement>('[data-pill-measure-id]')
		);

		if (pillNodes.length === 0) {
			collapsedVisiblePillIds = [];
			hiddenPillCount = 0;
			isPillRailMeasured = true;
			return;
		}

		const firstRowTop = pillNodes[0].offsetTop;
		let visibleIds = pillNodes
			.filter((node) => node.offsetTop === firstRowTop)
			.map((node) => Number(node.dataset.pillMeasureId));

		if (
			expandedAnsweredId !== null &&
			!visibleIds.includes(expandedAnsweredId) &&
			answeredPillQuestions.some((question) => question.id === expandedAnsweredId)
		) {
			visibleIds =
				visibleIds.length > 0
					? [...visibleIds.slice(0, visibleIds.length - 1), expandedAnsweredId]
					: [expandedAnsweredId];
		}

		collapsedVisiblePillIds = visibleIds;
		hiddenPillCount = Math.max(answeredPillQuestions.length - visibleIds.length, 0);
		isPillRailMeasured = true;

		if (hiddenPillCount === 0) {
			isPillRailExpanded = false;
		}
	}

	$effect(() => {
		const pillQuestionCount = answeredPillQuestions.length;
		isPillRailMeasured = false;
		void pillQuestionCount;
		void measureCollapsedPillRail();
	});

	$effect(() => {
		const expandedQuestionId = expandedAnsweredId;
		void expandedQuestionId;
		void measureCollapsedPillRail();
	});

	$effect(() => {
		if (!pillMeasurementContainer) return;

		const observer = new ResizeObserver(() => {
			void measureCollapsedPillRail();
		});

		observer.observe(pillMeasurementContainer);

		return () => {
			observer.disconnect();
		};
	});

	$effect(() => {
		if (!active) return;
		if (scrollToQuestionId == null) return;
		const questionId = scrollToQuestionId;

		void (async () => {
			expandedAnsweredId = questionId;
			await tick();
			document
				.getElementById(questionCardId(questionId))
				?.scrollIntoView({ behavior: 'smooth', block: 'center' });
			onscrollcomplete();
		})();
	});
</script>

<div class="flex max-h-[calc(100dvh-3rem)] flex-col gap-4 border-s border-slate-200 ps-6">
	<div>
		<h2 class="text-base font-semibold text-slate-950">Comprehension Checks</h2>
	</div>

	<div class="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1">
		{#if answeredPillQuestions.length > 0}
			<div class="relative">
				<div
					bind:this={pillMeasurementContainer}
					class="pointer-events-none invisible absolute inset-x-0 top-0"
					aria-hidden="true"
					inert
				>
					<div class="flex flex-wrap gap-2">
						{#each answeredPillQuestions as question (question.id)}
							{@const answered = answeredQuestions.get(question.id)}
							{#if answered}
								<div data-pill-measure-id={question.id}>
									<LectureVideoQuestionCard
										position={question.position}
										questionText={question.questionText}
										options={answered.options}
										state="answered"
										selectedOptionId={answered.selectedOptionId}
										correctOptionId={answered.correctOptionId}
										postAnswerText={answered.postAnswerText}
										expanded={false}
										active={expandedAnsweredId === question.id}
										ontoggleExpand={noop}
										onselectOption={noop}
									/>
								</div>
							{/if}
						{/each}
					</div>
				</div>

				<div id="answered-question-pill-rail" class="flex flex-wrap gap-2">
					{#each visiblePillQuestions as question (question.id)}
						{@const answered = answeredQuestions.get(question.id)}
						{#if answered}
							<div>
								<LectureVideoQuestionCard
									position={question.position}
									questionText={question.questionText}
									options={answered.options}
									state="answered"
									selectedOptionId={answered.selectedOptionId}
									correctOptionId={answered.correctOptionId}
									postAnswerText={answered.postAnswerText}
									expanded={false}
									active={expandedAnsweredId === question.id}
									ontoggleExpand={() => toggleExpandedAnswered(question.id)}
									onselectOption={noop}
								/>
							</div>
						{/if}
					{/each}
				</div>

				{#if hiddenPillCount > 0}
					<div class="mt-2">
						<button
							type="button"
							aria-controls="answered-question-pill-rail"
							aria-expanded={isPillRailExpanded}
							class="inline-flex cursor-pointer items-center rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-200"
							onclick={togglePillRailExpanded}
						>
							{#if isPillRailExpanded}
								Show less
							{:else}
								+{hiddenPillCount} more
							{/if}
						</button>
					</div>
				{/if}
			</div>
		{/if}

		{#each fullCardQuestions as question (question.id)}
			{@const answered = answeredQuestions.get(question.id)}
			{@const isAnswering = isCurrentAnswering(question.id)}
			{@const isFeedback = isCurrentFeedback(question.id)}
			<div id={questionCardId(question.id)}>
				{#if answered && !isFeedback}
					<LectureVideoQuestionCard
						position={question.position}
						questionText={question.questionText}
						options={answered.options}
						state="answered"
						selectedOptionId={answered.selectedOptionId}
						correctOptionId={answered.correctOptionId}
						postAnswerText={answered.postAnswerText}
						expanded={true}
						ontoggleExpand={() => toggleExpandedAnswered(question.id)}
						onselectOption={noop}
					/>
				{:else if isAnswering && currentQuestion}
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
				{:else if isFeedback && currentQuestion && currentContinuation}
					<LectureVideoQuestionCard
						position={question.position}
						questionText={question.questionText}
						options={currentQuestion.options}
						state="feedback"
						selectedOptionId={currentContinuation.option_id}
						correctOptionId={currentContinuation.correct_option_id}
						postAnswerText={currentContinuation.post_answer_text}
						expanded={false}
						onselectOption={noop}
						ontoggleExpand={noop}
						{...continueCardProps}
					/>
				{/if}
			</div>
		{/each}
	</div>
</div>
