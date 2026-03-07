<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { copy } from 'svelte-copy';
	import DOMPurify from '$lib/purify';
	import { sadToast } from '$lib/toast';
	import { SVG_DOCUMENT_PATTERN } from '$lib/svg';
	import hljs from 'highlight.js';
	import Sanitize from './Sanitize.svelte';

	export let source: string;
	export let isClosed = false;

	const highlightSvgCode = (source: string) => {
		const language = hljs.getLanguage('svg') ? 'svg' : 'plaintext';
		return hljs.highlight(source, { language }).value;
	};
	const SVG_PREVIEW_CARD_CLASS =
		'not-prose mb-4 max-w-[52rem] overflow-x-auto rounded-xl border border-gray-300 bg-gradient-to-b from-white to-slate-50 px-4 pt-3 pb-4';
	const SVG_PREVIEW_HEADER_CLASS = 'mb-3 flex items-center justify-between gap-4';
	const SVG_PREVIEW_LANGUAGE_CLASS = 'text-sm font-medium lowercase tracking-wide text-gray-600';
	const SVG_PREVIEW_COPY_BUTTON_CLASS =
		'inline-flex items-center gap-2 rounded-md border border-transparent bg-transparent px-1 py-1 text-sm font-medium text-gray-600 transition-colors hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500';
	const SVG_PREVIEW_CANVAS_CLASS = 'flex items-start justify-center';
	const SVG_PREVIEW_CANVAS_SVG_CLASS = 'block h-auto max-h-[32rem] max-w-full';

	let previewContainer: HTMLDivElement;
	let loading = false;
	let error = '';
	let renderedSource = source;
	let renderedClosed = isClosed;
	let canPreview = false;
	let copied = false;
	let copyResetTimeout: ReturnType<typeof setTimeout> | undefined;
	let previewMarkup = '';

	const decorateSvgMarkup = (markup: string) => {
		const parsed = new DOMParser().parseFromString(markup, 'image/svg+xml');
		const svg = parsed.documentElement;
		if (svg.tagName.toLowerCase() !== 'svg') {
			return '';
		}

		const currentClass = svg.getAttribute('class');
		svg.setAttribute(
			'class',
			currentClass
				? `${currentClass} ${SVG_PREVIEW_CANVAS_SVG_CLASS}`
				: SVG_PREVIEW_CANVAS_SVG_CLASS
		);

		// Give viewBox-only SVGs an intrinsic size so they don't collapse in preview.
		if (!svg.hasAttribute('width') || !svg.hasAttribute('height')) {
			const viewBox = svg
				.getAttribute('viewBox')
				?.trim()
				.split(/[\s,]+/);
			if (viewBox?.length === 4) {
				const width = Number(viewBox[2]);
				const height = Number(viewBox[3]);
				if (!svg.hasAttribute('width') && Number.isFinite(width) && width > 0) {
					svg.setAttribute('width', `${width}`);
				}
				if (!svg.hasAttribute('height') && Number.isFinite(height) && height > 0) {
					svg.setAttribute('height', `${height}`);
				}
			}
		}

		return new XMLSerializer().serializeToString(svg);
	};

	const getPreviewMarkup = (svgSource: string, closed: boolean) => {
		const trimmed = svgSource.trim();
		if (!closed || !SVG_DOCUMENT_PATTERN.test(trimmed)) {
			return '';
		}

		const sanitized = DOMPurify.sanitize(trimmed, {
			USE_PROFILES: { svg: true, svgFilters: true, html: false }
		});

		return typeof sanitized === 'string' ? decorateSvgMarkup(sanitized) : '';
	};

	// Keep this async so a synchronous innerHTML failure becomes a rejected Promise
	// that renderPreview's try/catch can handle.
	const renderInto = async (container: HTMLDivElement | undefined, markup: string) => {
		if (!container) {
			return;
		}

		container.innerHTML = markup;
	};

	const renderPreview = async () => {
		previewMarkup = getPreviewMarkup(source, isClosed);
		canPreview = previewMarkup.length > 0;
		loading = canPreview;
		error = '';

		try {
			await tick();
			if (canPreview) {
				await renderInto(previewContainer, previewMarkup);
			}
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to render SVG preview.';
			sadToast('Could not render SVG preview.');
			canPreview = false;
			previewMarkup = '';
		} finally {
			loading = false;
		}
	};

	const handleCopy = () => {
		copied = true;
		if (copyResetTimeout) {
			clearTimeout(copyResetTimeout);
		}
		copyResetTimeout = setTimeout(() => {
			copied = false;
			copyResetTimeout = undefined;
		}, 2000);
	};

	onMount(() => {
		void renderPreview();
	});

	onDestroy(() => {
		if (copyResetTimeout) {
			clearTimeout(copyResetTimeout);
		}
	});

	$: if (source !== renderedSource || isClosed !== renderedClosed) {
		renderedSource = source;
		renderedClosed = isClosed;
		void renderPreview();
	}
</script>

<div class={SVG_PREVIEW_CARD_CLASS}>
	<div class={SVG_PREVIEW_HEADER_CLASS}>
		<span class={SVG_PREVIEW_LANGUAGE_CLASS}>svg</span>
		<button
			type="button"
			class={SVG_PREVIEW_COPY_BUTTON_CLASS}
			aria-label="Copy SVG code"
			onclick={() => {}}
			use:copy={{ text: source, onCopy: handleCopy }}
		>
			<svg
				class="h-5 w-5 shrink-0 text-gray-500"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.75"
				aria-hidden="true"
			>
				<rect x="9" y="9" width="11" height="11" rx="2"></rect>
				<path d="M6 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"></path>
			</svg>
			<span>{copied ? 'Copied' : 'Copy code'}</span>
		</button>
	</div>

	{#if canPreview && !error}
		<div bind:this={previewContainer} class={SVG_PREVIEW_CANVAS_CLASS} class:hidden={loading}></div>
		{#if loading}
			<div
				class="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500"
			>
				Rendering SVG...
			</div>
		{/if}
	{:else}
		<pre
			class="m-0 overflow-x-auto rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm leading-5 whitespace-pre-wrap text-gray-900"><code
				class="language-svg"><Sanitize html={highlightSvgCode(source)} /></code
			></pre>
	{/if}
</div>
