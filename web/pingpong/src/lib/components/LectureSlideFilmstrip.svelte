<script
	lang="ts"
	generics="Q extends { client_id: string; slide_position: number; question_text: string }"
>
	import { browser } from '$app/environment';
	import { onDestroy } from 'svelte';
	import * as pdfjsLib from 'pdfjs-dist/legacy/build/pdf.mjs';
	import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.mjs?url';
	import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/pdf';
	import { QuestionCircleOutline } from 'flowbite-svelte-icons';
	import LectureSlideAddMenu from './LectureSlideAddMenu.svelte';

	type FilmstripPage = {
		id: number;
		position: number;
		content_kind?: 'slide' | 'image' | 'gif' | 'video';
		source_page_number?: number | null;
		media_url?: string | null;
		media_filename?: string | null;
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
	export let onInsertMedia: ((insertIndex: number) => void) | null = null;
	export let onReorder: ((fromPosition: number, toPosition: number) => void) | null = null;

	pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

	const THUMB_WIDTH = 220;
	const thumbnailKey = (page: FilmstripPage) => page.source_page_number ?? page.position;

	let pdfDocument: PDFDocumentProxy | null = null;
	let currentSourceUrl = '';
	let loadToken = 0;
	let thumbnails: Record<number, string> = {};
	let renderInProgress: Promise<void> | null = null;
	let draggedPosition: number | null = null;
	let reorderAnnouncement = '';

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

	const reorderPageBy = (page: FilmstripPage, pageIndex: number, delta: -1 | 1) => {
		const targetIndex = pageIndex + delta;
		const target = pages[targetIndex];
		if (!onReorder || !target) return;
		onReorder(page.position, target.position);
		reorderAnnouncement = '';
		queueMicrotask(() => {
			reorderAnnouncement = `Moved item ${pageIndex + 1} to position ${targetIndex + 1}.`;
		});
	};

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
				const key = thumbnailKey(page);
				if ((page.content_kind || 'slide') !== 'slide' || thumbnails[key]) {
					continue;
				}
				const pageNumber = Math.min(
					Math.max((page.source_page_number ?? page.position) + 1, 1),
					doc.numPages
				);
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
					thumbnails = { ...thumbnails, [key]: canvas.toDataURL('image/png') };
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
			await previousDocument.loadingTask.destroy();
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
				await doc.loadingTask.destroy();
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
		void pdfDocument?.loadingTask.destroy();
		pdfDocument = null;
	});
</script>

<div class="sr-only" aria-live="polite">{reorderAnnouncement}</div>

<div class="flex items-stretch gap-1.5 overflow-x-auto px-1 pt-2 pb-2">
	{#if onInsertMedia}
		<LectureSlideAddMenu
			insertIndex={0}
			label="Add content before the first item"
			{onInsertMedia}
		/>
	{/if}
	{#each pages as page, pageIndex (page.position)}
		{@const isSlideActive = !selectedQuestionClientId && page.position === selectedPosition}
		{@const pageQuestions = questionsByPosition[page.position] || []}
		<button
			type="button"
			draggable={onReorder !== null}
			ondragstart={() => (draggedPosition = page.position)}
			ondragover={(event) => {
				if (onReorder) event.preventDefault();
			}}
			ondrop={(event) => {
				event.preventDefault();
				if (draggedPosition !== null) onReorder?.(draggedPosition, page.position);
				draggedPosition = null;
			}}
			ondragend={() => (draggedPosition = null)}
			onkeydown={(event) => {
				if (!event.altKey || !onReorder) return;
				if (event.key === 'ArrowLeft' && pageIndex > 0) {
					event.preventDefault();
					reorderPageBy(page, pageIndex, -1);
				} else if (event.key === 'ArrowRight' && pageIndex < pages.length - 1) {
					event.preventDefault();
					reorderPageBy(page, pageIndex, 1);
				}
			}}
			onclick={() => onSelectSlide(page.position)}
			aria-label={`Slide ${pageIndex + 1}`}
			aria-pressed={isSlideActive}
			aria-keyshortcuts={onReorder ? 'Alt+ArrowLeft Alt+ArrowRight' : undefined}
			title={onReorder ? 'Use Alt+Left or Alt+Right to reorder' : undefined}
			class="group relative flex w-32 shrink-0 flex-col overflow-hidden rounded-xl border bg-white transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/15 {isSlideActive
				? 'border-gray-900 shadow-md'
				: 'border-gray-200 hover:border-gray-400 hover:shadow-sm'}"
		>
			<div class="relative aspect-video w-full overflow-hidden bg-gray-50">
				{#if page.content_kind === 'video' && page.media_url}
					<video src={page.media_url} class="h-full w-full object-contain" muted preload="metadata"
					></video>
				{:else if page.content_kind !== 'slide' && page.media_url}
					<img
						src={page.media_url}
						alt={page.media_filename || `${page.content_kind} ${pageIndex + 1}`}
						class="h-full w-full object-contain"
						draggable="false"
					/>
				{:else if (page.content_kind || 'slide') === 'slide' && thumbnails[thumbnailKey(page)]}
					<img
						src={thumbnails[thumbnailKey(page)]}
						alt={`Slide ${pageIndex + 1} thumbnail`}
						class="h-full w-full object-contain"
						draggable="false"
					/>
				{:else}
					<div class="flex h-full w-full items-center justify-center text-xs text-gray-400">
						{page.content_kind === 'video'
							? 'Video'
							: page.content_kind === 'gif'
								? 'GIF'
								: page.content_kind === 'image'
									? 'Image'
									: `Slide ${pageIndex + 1}`}
					</div>
				{/if}
				<span
					class="absolute top-1.5 left-1.5 rounded-md bg-gray-900/85 px-1.5 py-0.5 text-[10px] leading-none font-semibold text-white backdrop-blur-sm"
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
					{page.content_kind === 'slide'
						? `Slide ${(page.source_page_number ?? pageIndex) + 1}`
						: page.media_filename || page.content_kind}
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
				<span class="text-[10px] leading-none font-semibold">Q{number}</span>
			</button>
		{/each}

		{#if onInsertMedia || onAddQuestion}
			<LectureSlideAddMenu
				insertIndex={pageIndex + 1}
				questionPosition={page.position}
				label={`Add content after item ${pageIndex + 1}`}
				{onInsertMedia}
				{onAddQuestion}
			/>
		{/if}
	{/each}
</div>
