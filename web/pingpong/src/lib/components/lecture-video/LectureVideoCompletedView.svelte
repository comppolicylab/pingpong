<script lang="ts">
	import { getLectureVideoHistory, expandResponse } from '$lib/api';
	import { loading as globalLoading } from '$lib/stores/general';
	import type { LectureVideoInteractionHistoryItem } from '$lib/api';
	import { Spinner } from 'flowbite-svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import LectureVideoQuestionCard from './LectureVideoQuestionCard.svelte';

	type ReviewQuestion = {
		id: number;
		position: number;
		questionText: string;
		options: { id: number; option_text: string; post_answer_text?: string | null }[];
		selectedOptionId: number | null;
		correctOptionId: number | null;
	};

	let {
		classId,
		threadId,
		initialInteractions = null
	}: {
		classId: number;
		threadId: number;
		initialInteractions?: LectureVideoInteractionHistoryItem[] | null;
	} = $props();

	let loading: boolean = $state(true);
	let interactions: LectureVideoInteractionHistoryItem[] = $state([]);
	let errorMsg: string | null = $state(null);

	function buildReviewQuestions(items: LectureVideoInteractionHistoryItem[]): ReviewQuestion[] {
		const questionMap = new SvelteMap<number, Omit<ReviewQuestion, 'position'>>();

		for (const item of items) {
			if (item.question_id == null) continue;

			const question = questionMap.get(item.question_id) ?? {
				id: item.question_id,
				questionText: item.question_text ?? '',
				options: [],
				selectedOptionId: null,
				correctOptionId: null
			};

			if (item.question_text) {
				question.questionText = item.question_text;
			}
			if (item.question_options && item.question_options.length > 0) {
				question.options = item.question_options;
			}
			if (item.correct_option_id != null) {
				question.correctOptionId = item.correct_option_id;
			}
			if (item.event_type === 'answer_submitted' && item.option_id != null) {
				question.selectedOptionId = item.option_id;
				if (
					question.options.length === 0 &&
					item.option_text &&
					!question.options.some((option) => option.id === item.option_id)
				) {
					question.options = [{ id: item.option_id, option_text: item.option_text }];
				}
			}

			questionMap.set(item.question_id, question);
		}

		return Array.from(questionMap.values(), (question, index) => ({
			...question,
			position: index + 1
		}));
	}

	let reviewQuestions = $derived(buildReviewQuestions(interactions));

	$effect(() => {
		let cancelled = false;

		async function fetchHistory() {
			if (initialInteractions != null) {
				if (!cancelled) {
					interactions = initialInteractions;
					errorMsg = null;
					loading = false;
				}
				return;
			}

			loading = true;
			errorMsg = null;

			try {
				const response = await getLectureVideoHistory(fetch, classId, threadId);
				const expanded = expandResponse(response);

				if (cancelled) return;

				if (expanded.error) {
					errorMsg = expanded.error.detail || 'Failed to load history';
					return;
				}

				interactions = expanded.data.interactions;
			} catch {
				if (!cancelled) {
					errorMsg = 'Failed to load history';
				}
			} finally {
				if (!cancelled) {
					loading = false;
				}
			}
		}

		void fetchHistory();

		return () => {
			cancelled = true;
		};
	});
</script>

<div class="mx-auto h-full max-w-3xl overflow-y-auto px-4 py-6">
	{#if errorMsg}
		<div class="flex h-full items-center justify-center">
			<p class="text-sm text-red-600">{errorMsg}</p>
		</div>
	{:else if loading && !$globalLoading}
		<div class="flex h-full min-h-48 items-center justify-center">
			<div class="flex items-center gap-3 text-sm text-slate-500">
				<Spinner color="gray" class="h-4 w-4" />
				<span>Loading completed lecture review...</span>
			</div>
		</div>
	{:else if !loading}
		<div class="flex flex-col gap-4">
			{#each reviewQuestions as question (question.id)}
				<LectureVideoQuestionCard
					position={question.position}
					questionText={question.questionText}
					options={question.options}
					state="answered"
					selectedOptionId={question.selectedOptionId}
					correctOptionId={question.correctOptionId}
					postAnswerText={null}
					expanded={true}
					ontoggleExpand={() => {}}
					onselectOption={() => {}}
				/>
			{/each}
		</div>
	{/if}
</div>
