<script lang="ts">
	import { getLectureVideoHistory, expandResponse } from '$lib/api';
	import { loading as globalLoading } from '$lib/stores/general';
	import type { LectureVideoInteractionHistoryItem } from '$lib/api';
	import { mergeQuestionOptions } from '$lib/utils/lecture-video';
	import { Spinner } from 'flowbite-svelte';
	import { ClipboardListOutline } from 'flowbite-svelte-icons';
	import { SvelteMap } from 'svelte/reactivity';
	import LectureVideoQuestionCard from './LectureVideoQuestionCard.svelte';

	type ReviewQuestion = {
		id: number;
		position: number;
		questionText: string;
		options: { id: number; option_text: string; post_answer_text?: string | null }[];
		selectedOptionId: number | null;
		correctOptionId: number | null;
		postAnswerText: string | null;
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
				correctOptionId: null,
				postAnswerText: null
			};

			if (item.question_text) {
				question.questionText = item.question_text;
			}
			if (item.question_options && item.question_options.length > 0) {
				question.options = mergeQuestionOptions(question.options, item.question_options);
			}
			if (item.correct_option_id != null) {
				question.correctOptionId = item.correct_option_id;
			}
			if (item.event_type === 'answer_submitted' && item.option_id != null) {
				question.selectedOptionId = item.option_id;
				question.postAnswerText =
					question.options.find((option) => option.id === item.option_id)?.post_answer_text ?? null;
				if (question.options.length === 0 && item.option_text) {
					question.options = [
						{
							id: item.option_id,
							option_text: item.option_text,
							post_answer_text: question.postAnswerText
						}
					];
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
		{#if reviewQuestions.length > 0}
			<div class="flex flex-col gap-4">
				{#each reviewQuestions as question (question.id)}
					<LectureVideoQuestionCard
						position={question.position}
						questionText={question.questionText}
						options={question.options}
						state="answered"
						selectedOptionId={question.selectedOptionId}
						correctOptionId={question.correctOptionId}
						postAnswerText={question.postAnswerText}
					/>
				{/each}
			</div>
		{:else}
			<div class="flex h-full min-h-48 items-center justify-center px-4 py-8">
				<div class="flex max-w-sm flex-col items-center text-center">
					<div
						class="mb-3 flex size-12 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-400"
					>
						<ClipboardListOutline class="size-6" />
					</div>
					<h2 class="text-sm font-semibold text-slate-900">No comprehension checks</h2>
					<p class="mt-1 max-w-72 text-sm text-slate-500">
						There are no completed comprehension checks to review for this lecture.
					</p>
				</div>
			</div>
		{/if}
	{/if}
</div>
