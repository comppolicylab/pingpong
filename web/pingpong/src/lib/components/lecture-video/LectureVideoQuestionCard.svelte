<script lang="ts">
	import { CheckOutline } from 'flowbite-svelte-icons';
	import { tick, type Snippet } from 'svelte';

	type QuestionOption = {
		id: number;
		option_text: string;
		post_answer_text?: string | null;
	};

	type ReviewState = 'selected-correct' | 'selected-wrong' | 'correct' | 'neutral';

	type ReviewStyle = {
		row: string;
		divider: string;
		marker: string;
		text: string;
		feedback: string;
		showCheck: boolean;
	};

	type Props = {
		position: number;
		questionText: string;
		options: QuestionOption[];
		state: 'answering' | 'feedback' | 'answered';
		selectedOptionId: number | null;
		correctOptionId: number | null;
		postAnswerText: string | null;
		answeringDisabled?: boolean;
		showContinue?: boolean;
		continueDisabled?: boolean;
		onselectOption?: (optionId: number) => void;
		oncontinue?: () => void;
		headerTrailing?: Snippet;
	};

	let {
		position,
		questionText,
		options = [],
		state: cardState,
		selectedOptionId = null,
		correctOptionId = null,
		postAnswerText = null,
		answeringDisabled = false,
		showContinue = false,
		continueDisabled = false,
		onselectOption,
		oncontinue,
		headerTrailing
	}: Props = $props();

	let pendingOptionId: number | null = $state(null);
	let checkButton: HTMLButtonElement | null = $state(null);

	const cardClass = 'rounded-lg border border-slate-200 bg-white p-4';
	const questionLabelClass = 'text-xs font-semibold uppercase tracking-widest text-slate-400';
	const questionTextClass = 'mt-1 text-sm font-medium text-slate-900';
	const actionButtonClass =
		'mt-3 w-full rounded-lg px-6 py-2.5 text-sm font-medium transition-colors';
	const reviewStyles: Record<ReviewState, ReviewStyle> = {
		'selected-correct': {
			row: 'bg-emerald-50',
			divider: 'bg-emerald-700',
			marker:
				'inline-flex h-6 shrink-0 items-center justify-center gap-1 rounded-full border border-emerald-700 bg-emerald-700 px-1.5 text-[10px] font-semibold text-white',
			text: 'text-emerald-700',
			feedback: 'mt-1 text-sm leading-5 text-emerald-700',
			showCheck: true
		},
		'selected-wrong': {
			row: 'bg-red-50',
			divider: 'bg-red-700',
			marker:
				'flex size-6 shrink-0 items-center justify-center rounded-full border border-red-700 bg-red-700 text-[10px] font-semibold text-white',
			text: 'text-red-700',
			feedback: 'mt-1 text-sm leading-5 text-red-700',
			showCheck: false
		},
		correct: {
			row: '',
			divider: '',
			marker:
				'inline-flex h-6 shrink-0 items-center justify-center gap-1 rounded-full border border-emerald-700 bg-white px-1.5 text-[10px] font-semibold text-emerald-700',
			text: 'text-emerald-700',
			feedback: '',
			showCheck: true
		},
		neutral: {
			row: '',
			divider: '',
			marker:
				'flex size-6 shrink-0 items-center justify-center rounded-full border border-slate-300 bg-white text-[10px] font-semibold text-slate-500',
			text: 'text-slate-500',
			feedback: '',
			showCheck: false
		}
	};

	function optionLabel(index: number): string {
		return String.fromCharCode(65 + index);
	}

	async function selectPendingOption(optionId: number) {
		pendingOptionId = optionId;
		await tick();
		checkButton?.scrollIntoView({ block: 'end', behavior: 'smooth' });
	}

	function handleCheck() {
		if (pendingOptionId !== null && onselectOption) {
			onselectOption(pendingOptionId);
			pendingOptionId = null;
		}
	}

	function optionFeedbackText(option: QuestionOption): string | null {
		if (option.id === selectedOptionId) {
			return option.post_answer_text ?? postAnswerText ?? null;
		}
		return option.post_answer_text ?? null;
	}

	function optionReviewState(optionId: number): ReviewState {
		if (optionId === selectedOptionId && correctOptionId != null && optionId === correctOptionId) {
			return 'selected-correct';
		}
		if (optionId === selectedOptionId && correctOptionId != null && optionId !== correctOptionId) {
			return 'selected-wrong';
		}
		if (correctOptionId != null && optionId === correctOptionId) {
			return 'correct';
		}
		return 'neutral';
	}

	function answerOptionButtonClass(disabled: boolean): string {
		return [
			'flex w-full items-center gap-3 py-3 pr-1 pl-2.5 text-left text-sm font-medium transition-colors',
			disabled
				? 'cursor-not-allowed text-slate-400 opacity-70'
				: 'cursor-pointer text-slate-900 hover:bg-slate-50'
		].join(' ');
	}

	function answerOptionMarkerClass(isSelected: boolean, disabled: boolean): string {
		if (isSelected) {
			return 'border-blue-600 bg-blue-600 text-white group-hover/option-row:outline-2 group-hover/option-row:outline-offset-2 group-hover/option-row:outline-blue-500';
		}
		if (disabled) {
			return 'border-slate-200 bg-white text-slate-300';
		}
		return 'border-slate-500 bg-white text-slate-600 group-hover/option-row:outline-2 group-hover/option-row:outline-offset-2 group-hover/option-row:outline-blue-500';
	}
</script>

<div class="w-full">
	{#if cardState === 'answering'}
		<div class={cardClass}>
			{@render questionHeader('mb-4')}
			<div class="border-b border-slate-200">
				{#each options as option, index (option.id)}
					{@const isSelected = pendingOptionId === option.id}
					<div class="group/option-row relative">
						<span
							class="pointer-events-none absolute inset-x-0 -top-px z-0 h-px bg-slate-200 transition-all group-hover/option-row:z-20 group-hover/option-row:h-0.5 group-hover/option-row:bg-slate-400"
						></span>
						<span
							class="pointer-events-none absolute inset-x-0 -bottom-px z-20 h-0 bg-transparent transition-all group-hover/option-row:h-0.5 group-hover/option-row:bg-slate-400"
						></span>
						<button
							type="button"
							class="{answerOptionButtonClass(answeringDisabled)} relative z-10"
							disabled={answeringDisabled}
							aria-pressed={isSelected}
							onclick={() => selectPendingOption(option.id)}
						>
							<span
								class="flex size-6 shrink-0 items-center justify-center rounded-full border-2 text-[10px] leading-none font-semibold {answerOptionMarkerClass(
									isSelected,
									answeringDisabled
								)}"
							>
								{optionLabel(index)}
							</span>
							<span class="min-w-0 flex-1 text-sm leading-6 font-medium text-slate-900">
								{option.option_text}
							</span>
						</button>
					</div>
				{/each}
			</div>
			{#if pendingOptionId !== null}
				<button
					bind:this={checkButton}
					type="button"
					class="{actionButtonClass} cursor-pointer bg-blue-600 text-white hover:bg-blue-700"
					onclick={handleCheck}
				>
					Check
				</button>
			{/if}
		</div>
	{:else}
		<div class={cardClass}>
			{@render questionHeader('mb-3')}
			<div class="flex flex-col divide-y divide-slate-200 border-y border-slate-200">
				{#each options as option, index (option.id)}
					{@const reviewState = optionReviewState(option.id)}
					{@const feedbackText = optionFeedbackText(option)}
					{@const reviewStyle = reviewStyles[reviewState]}
					<div class="relative py-2.5 pr-2 pl-3 {reviewStyle.row}">
						{#if reviewStyle.divider}
							<span
								class="pointer-events-none absolute inset-x-0 -top-px h-px {reviewStyle.divider}"
							></span>
							<span
								class="pointer-events-none absolute inset-x-0 -bottom-px h-px {reviewStyle.divider}"
							></span>
						{/if}
						<div class="flex items-start gap-2.5">
							<div class="flex w-9 shrink-0 justify-start">
								<span class={reviewStyle.marker}>
									{#if reviewStyle.showCheck}
										<CheckOutline
											class="h-3 w-3 shrink-0 {reviewState === 'selected-correct'
												? 'text-white'
												: 'text-emerald-700'}"
											strokeWidth="3"
										/>
									{/if}
									{optionLabel(index)}
								</span>
							</div>
							<div class="min-w-0 flex-1">
								<div class="text-sm leading-6 font-medium {reviewStyle.text}">
									{option.option_text}
								</div>
								{#if feedbackText && reviewStyle.feedback}
									<div class={reviewStyle.feedback}>{feedbackText}</div>
								{/if}
							</div>
						</div>
					</div>
				{/each}
			</div>
			{#if showContinue}
				<button
					type="button"
					class="{actionButtonClass} {continueDisabled
						? 'cursor-not-allowed bg-slate-300 text-slate-500'
						: 'cursor-pointer bg-blue-600 text-white hover:bg-blue-700'}"
					disabled={continueDisabled}
					onclick={oncontinue}
				>
					Continue
				</button>
			{/if}
		</div>
	{/if}
</div>

{#snippet questionHeader(marginClass: string)}
	<div class="{marginClass} flex items-start justify-between gap-3">
		<div class="min-w-0 flex-1">
			<div class={questionLabelClass}>Question {position}</div>
			<div class={questionTextClass}>{questionText}</div>
		</div>
		{@render headerTrailing?.()}
	</div>
{/snippet}
