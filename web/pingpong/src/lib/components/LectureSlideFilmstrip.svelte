<script
	lang="ts"
	generics="Q extends { client_id: string; slide_position: number; question_text: string }"
>
	import { browser } from '$app/environment';
	import { onDestroy } from 'svelte';
	import * as pdfjsLib from 'pdfjs-dist/legacy/build/pdf.mjs';
	import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.mjs?url';
	import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/pdf';
	import { QuestionCircleOutline, PlusOutline } from 'flowbite-svelte-icons';

	type FilmstripPage = {
		position: number;
		narration_text?: string | null;
	};

	export let sourceUrl = '';
	export let pages: FilmstripPage[] = [];
	export let questions: Q[] = [];
	export let selectedPosition = 0;
	export let selectedQuestionClientId: string | null = null;
	export let onSelectSlide: (position: number) => void = () => {};
	export let onSelectQuestion: (question: Q) => void = () => {};
	export let onAddQuestion: ((position: number) => void) | null = null;

	pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

	const THUMB_WIDTH = 220;

	let pdfDocument: PDFDocumentProxy | null = null;
	let currentSourceUrl = '';
	let loadToken = 0;
	let thumbnails: Record<number, string> = {};
	let renderInProgress: Promise<void> | null = null;

	const questionSequence = (clientId: string) => {
		const sequence = Number(clientId.replace('lecture-slide-question-draft-', ''));
		return Number.isFinite(sequence) ? sequence : 0;
	};

	$: orderedQuestions = [...questions].sort((left, right) =>
		left.slide_position === right.slide_position
			? questionSequence(left.client_id) - questionSequence(right.client_id)
			: left.slide_position - right.slide_position
	);
	$: questionsByPosition = orderedQuestions.reduce(
		(grouped, question) => {
			grouped[question.slide_position] = [...(grouped[question.slide_position] || []), question];
			return grouped;
		},
		{} as Record<number, Q[]>
	);

	const questionNumber = (questionClientId: string) =>
		orderedQuestions.findIndex((question) => question.client_id === questionClientId) + 1;

	const renderThumbnails = async (doc: PDFDocumentProxy) => {
		const token = loadToken;
		if (renderInProgress) {
			await renderInProgress;
			if (token === loadToken) {
				await renderThumbnails(doc);
			}
			return;
		}
		const renderPromise = (async () => {
			for (const page of pages) {
				if (token !== loadToken) {
					return;
				}
				if (thumbnails[page.position]) {
					continue;
				}
				const pageNumber = Math.min(Math.max(page.position + 1, 1), doc.numPages);
				try {
					const pdfPage = await doc.getPage(pageNumber);
					const base = pdfPage.getViewport({ scale: 1 });
					const scale = THUMB_WIDTH / base.width;
					const viewport = pdfPage.getViewport({ scale });
					const canvas = document.createElement('canvas');
					canvas.width = Math.floor(viewport.width);
					canvas.height = Math.floor(viewport.height);
					const context = canvas.getContext('2d');
					if (!context) {
						continue;
					}
					await pdfPage.render({ canvas, canvasContext: context, viewport }).promise;
					if (token !== loadToken) {
						return;
					}
					thumbnails = { ...thumbnails, [page.position]: canvas.toDataURL('image/png') };
				} catch {
					// Skip thumbnails that fail to render; the label fallback is shown instead.
				}
			}
		})();
		renderInProgress = renderPromise;
		try {
			await renderPromise;
		} finally {
			if (renderInProgress === renderPromise) {
				renderInProgress = null;
			}
		}
	};

	const loadDocument = async (url: string) => {
		const token = ++loadToken;
		currentSourceUrl = url;
		thumbnails = {};
		const previousDocument = pdfDocument;
		pdfDocument = null;
		if (previousDocument) {
			await previousDocument.destroy();
		}
		if (token !== loadToken) {
			return;
		}
		if (!url) {
			return;
		}
		try {
			const loadingTask = pdfjsLib.getDocument({ url, withCredentials: true });
			const doc = await loadingTask.promise;
			if (token !== loadToken) {
				await doc.destroy();
				return;
			}
			pdfDocument = doc;
			await renderThumbnails(doc);
		} catch {
			// Leave thumbnails empty; label fallbacks render in their place.
		}
	};

	$: if (browser && sourceUrl !== currentSourceUrl) {
		void loadDocument(sourceUrl);
	}

	$: if (browser && pdfDocument && pages.length) {
		void renderThumbnails(pdfDocument);
	}

	onDestroy(() => {
		loadToken += 1;
		void pdfDocument?.destroy();
		pdfDocument = null;
	});
</script>

<div class="flex items-stretch gap-1.5 overflow-x-auto px-1 pb-2 pt-2">
	{#each pages as page, pageIndex (page.position)}
		{@const isSlideActive = !selectedQuestionClientId && page.position === selectedPosition}
		{@const pageQuestions = questionsByPosition[page.position] || []}
		<button
			type="button"
			onclick={() => onSelectSlide(page.position)}
			aria-label={`Slide ${pageIndex + 1}`}
			aria-pressed={isSlideActive}
			class="group relative flex w-32 shrink-0 flex-col overflow-hidden rounded-xl border bg-white transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/15 {isSlideActive
				? 'border-gray-900 shadow-md'
				: 'border-gray-200 hover:border-gray-400 hover:shadow-sm'}"
		>
			<div class="relative aspect-video w-full overflow-hidden bg-gray-50">
				{#if thumbnails[page.position]}
					<img
						src={thumbnails[page.position]}
						alt={`Slide ${pageIndex + 1} thumbnail`}
						class="h-full w-full object-contain"
						draggable="false"
					/>
				{:else}
					<div class="flex h-full w-full items-center justify-center text-xs text-gray-400">
						Slide {pageIndex + 1}
					</div>
				{/if}
				<span
					class="absolute left-1.5 top-1.5 rounded-md bg-gray-900/85 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white backdrop-blur-sm"
				>
					{pageIndex + 1}
				</span>
			</div>
			<div class="px-2 py-1.5">
				<span
					class="block truncate text-[11px] font-medium {isSlideActive
						? 'text-gray-900'
						: 'text-gray-600'}"
				>
					Slide {pageIndex + 1}
				</span>
			</div>
		</button>

		{#each pageQuestions as question (question.client_id)}
			{@const isQuestionActive = selectedQuestionClientId === question.client_id}
			{@const number = questionNumber(question.client_id)}
			<button
				type="button"
				onclick={() => onSelectQuestion(question)}
				aria-label={`Question ${number} after slide ${pageIndex + 1}`}
				aria-pressed={isQuestionActive}
				title={question.question_text || `Question ${number}`}
				class="group flex w-14 shrink-0 flex-col items-center justify-center gap-1 rounded-xl border border-dashed transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/15 {isQuestionActive
					? 'border-gray-900 bg-gray-900 text-white shadow-md'
					: 'border-gray-300 bg-gray-50 text-gray-700 hover:border-gray-600 hover:bg-white hover:shadow-sm'}"
			>
				<QuestionCircleOutline class="h-5 w-5" />
				<span class="text-[10px] font-semibold leading-none">Q{number}</span>
			</button>
		{/each}

		{#if onAddQuestion}
			<button
				type="button"
				onclick={() => onAddQuestion?.(page.position)}
				aria-label={`Add a question after slide ${pageIndex + 1}`}
				title={`Add a question after slide ${pageIndex + 1}`}
				class="group/add flex w-6 shrink-0 items-center justify-center self-stretch rounded-lg text-gray-300 hover:bg-gray-50 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/15"
			>
				<span
					class="flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-gray-300 bg-white group-hover/add:border-gray-700 group-hover/add:bg-gray-900 group-hover/add:text-white"
				>
					<PlusOutline class="h-3 w-3" />
				</span>
			</button>
		{/if}
	{/each}
</div>
