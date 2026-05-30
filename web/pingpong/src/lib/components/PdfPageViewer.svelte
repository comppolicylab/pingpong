<script lang="ts">
	import { browser } from '$app/environment';
	import { onDestroy, tick } from 'svelte';
	import * as pdfjsLib from 'pdfjs-dist';
	import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url';
	import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist/types/src/pdf';

	export let sourceUrl = '';
	export let pageNumber = 1;
	export let slideLabel = '';
	export let previousDisabled = false;
	export let nextDisabled = false;
	export let onPrevious: (() => void) | null = null;
	export let onNext: (() => void) | null = null;

	let container: HTMLDivElement;
	let canvas: HTMLCanvasElement;
	let pdfDocument: PDFDocumentProxy | null = null;
	let renderTask: RenderTask | null = null;
	let resizeObserver: ResizeObserver | null = null;
	let currentSourceUrl = '';
	let loadToken = 0;
	let renderToken = 0;
	let loading = false;
	let errorMessage = '';
	let pageWidth = '100%';

	pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

	const destroyDocument = async () => {
		renderTask?.cancel();
		renderTask = null;
		if (pdfDocument) {
			await pdfDocument.destroy();
			pdfDocument = null;
		}
	};

	const renderPage = async () => {
		if (!browser || !pdfDocument || !canvas || !container) {
			return;
		}

		const token = ++renderToken;
		const clampedPageNumber = Math.min(Math.max(pageNumber, 1), pdfDocument.numPages);
		errorMessage = '';
		await tick();

		let page: PDFPageProxy;
		try {
			page = await pdfDocument.getPage(clampedPageNumber);
		} catch (error) {
			if (token === renderToken) {
				errorMessage = error instanceof Error ? error.message : 'Could not load this page.';
			}
			return;
		}
		if (token !== renderToken) {
			return;
		}

		renderTask?.cancel();
		const baseViewport = page.getViewport({ scale: 1 });
		const availableWidth = Math.max(container.clientWidth - 32, 320);
		const scale = Math.min(availableWidth / baseViewport.width, 2);
		const viewport = page.getViewport({ scale });
		const outputScale = window.devicePixelRatio || 1;
		const context = canvas.getContext('2d');
		if (!context) {
			errorMessage = 'Could not render this page.';
			return;
		}

		canvas.width = Math.floor(viewport.width * outputScale);
		canvas.height = Math.floor(viewport.height * outputScale);
		pageWidth = `${Math.floor(viewport.width)}px`;
		canvas.style.width = pageWidth;
		canvas.style.height = `${Math.floor(viewport.height)}px`;
		context.setTransform(outputScale, 0, 0, outputScale, 0, 0);

		try {
			renderTask = page.render({ canvas, canvasContext: context, viewport });
			await renderTask.promise;
		} catch (error) {
			if (
				token === renderToken &&
				error instanceof Error &&
				error.name !== 'RenderingCancelledException'
			) {
				errorMessage = error.message || 'Could not render this page.';
			}
		} finally {
			if (token === renderToken) {
				renderTask = null;
			}
		}
	};

	const loadDocument = async (url: string) => {
		const token = ++loadToken;
		currentSourceUrl = url;
		loading = true;
		errorMessage = '';
		await destroyDocument();
		if (!url) {
			loading = false;
			return;
		}

		try {
			const loadingTask = pdfjsLib.getDocument({ url, withCredentials: true });
			const document = await loadingTask.promise;
			if (token !== loadToken) {
				await document.destroy();
				return;
			}
			pdfDocument = document;
			await renderPage();
		} catch (error) {
			if (token === loadToken) {
				errorMessage = error instanceof Error ? error.message : 'Could not load this PDF.';
			}
		} finally {
			if (token === loadToken) {
				loading = false;
			}
		}
	};

	$: if (browser && sourceUrl !== currentSourceUrl) {
		void loadDocument(sourceUrl);
	}

	$: if (browser && pdfDocument && pageNumber) {
		void renderPage();
	}

	$: if (browser && container && !resizeObserver) {
		resizeObserver = new ResizeObserver(() => {
			void renderPage();
		});
		resizeObserver.observe(container);
	}

	onDestroy(() => {
		loadToken += 1;
		renderToken += 1;
		resizeObserver?.disconnect();
		void destroyDocument();
	});
</script>

<div
	bind:this={container}
	class="flex h-full min-h-[420px] w-full items-start justify-center overflow-auto bg-gray-100 p-4"
>
	{#if errorMessage}
		<div class="mt-8 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
			{errorMessage}
		</div>
	{:else if loading}
		<div class="mt-8 text-sm text-gray-600">Loading slide...</div>
	{/if}
	<div class:hidden={!!errorMessage || loading} class="flex flex-col gap-3" style:width={pageWidth}>
		<canvas bind:this={canvas} class="bg-white shadow-md"></canvas>
		<div class="flex w-full items-center justify-between gap-3">
			<button
				type="button"
				class="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
				disabled={previousDisabled}
				onclick={() => onPrevious?.()}
			>
				Previous
			</button>
			<div class="min-w-0 flex-1 text-center text-xs font-medium text-gray-600">
				{slideLabel}
			</div>
			<button
				type="button"
				class="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
				disabled={nextDisabled}
				onclick={() => onNext?.()}
			>
				Next
			</button>
		</div>
	</div>
</div>
