<script lang="ts">
	import { afterUpdate, mount, onDestroy, tick, unmount } from 'svelte';
	import type { InlineWebSource } from '$lib/content';
	import { parseMarkdownSegments, type MarkdownSegment } from '$lib/markdown-segments';
	import MermaidDiagram from './MermaidDiagram.svelte';
	import MermaidStreaming from './MermaidStreaming.svelte';
	import Sanitize from './Sanitize.svelte';
	import SvgDiagram from './SvgDiagram.svelte';
	import WebSourceChip from './WebSourceChip.svelte';
	import 'katex/dist/katex.min.css';

	export let content = '';
	export let syntax = true;
	export let latex = false;
	export let inlineWebSources: InlineWebSource[] = [];

	let container: HTMLDivElement;
	let mountedChips: WebSourceChip[] = [];
	let mountedDiagrams: Array<{ component: object; placeholderId: string }> = [];
	let wrappedDiagramMountVersion = 0;

	$: segments = parseMarkdownSegments(content, { syntax, latex });
	$: wrappedDiagramSignature = JSON.stringify(
		segments
			.filter(
				(segment): segment is Extract<MarkdownSegment, { type: 'wrapped-diagram' }> =>
					segment.type === 'wrapped-diagram'
			)
			.map((segment) => ({
				placeholderId: segment.placeholderId,
				type: segment.diagram.type,
				source: segment.diagram.source
			}))
	);
	let mountedWrappedDiagramSignature = '';

	const destroyInlineWebSources = () => {
		mountedChips.forEach((chip) => chip.$destroy());
		mountedChips = [];
	};

	const destroyMountedDiagrams = async () => {
		const mounted = mountedDiagrams;
		mountedDiagrams = [];
		await Promise.all(mounted.map(({ component }) => unmount(component)));
	};

	// Replace placeholder spans from parseTextContent with live WebSourceChip instances.
	const mountInlineWebSources = async () => {
		if (!inlineWebSources.length || !container) {
			destroyInlineWebSources();
			return;
		}

		destroyInlineWebSources();
		await tick();
		if (!container) {
			return;
		}

		const inlineWebSourcesByIndex = new Map(
			inlineWebSources.map((source) => [source.index, source])
		);

		const placeholders = container.querySelectorAll('[data-web-source-index]');

		placeholders.forEach((placeholder) => {
			const index = Number(placeholder.getAttribute('data-web-source-index'));
			const source = inlineWebSourcesByIndex.get(index);

			if (!source) {
				return;
			}

			mountedChips.push(
				new WebSourceChip({
					target: placeholder as HTMLElement,
					props: { source: source.source, type: 'chip' }
				})
			);
		});
	};

	const mountWrappedDiagrams = async () => {
		const mountVersion = ++wrappedDiagramMountVersion;
		if (wrappedDiagramSignature === mountedWrappedDiagramSignature) {
			return;
		}

		if (!container) {
			await destroyMountedDiagrams();
			mountedWrappedDiagramSignature = '';
			return;
		}

		await destroyMountedDiagrams();
		if (mountVersion !== wrappedDiagramMountVersion) {
			return;
		}

		await tick();
		if (!container || mountVersion !== wrappedDiagramMountVersion) {
			return;
		}

		const wrappedDiagramSegments = segments.filter(
			(segment): segment is Extract<MarkdownSegment, { type: 'wrapped-diagram' }> =>
				segment.type === 'wrapped-diagram'
		);

		if (!wrappedDiagramSegments.length) {
			mountedWrappedDiagramSignature = wrappedDiagramSignature;
			return;
		}

		for (const segment of wrappedDiagramSegments) {
			const placeholder = container.querySelector(
				`[data-markdown-diagram-placeholder="${segment.placeholderId}"]`
			);
			if (!(placeholder instanceof HTMLElement) || mountVersion !== wrappedDiagramMountVersion) {
				continue;
			}

			const component =
				segment.diagram.type === 'svg-complete' || segment.diagram.type === 'svg-streaming'
					? mount(SvgDiagram, {
							target: placeholder,
							props: {
								source: segment.diagram.source,
								isClosed: segment.diagram.type === 'svg-complete'
							}
						})
					: segment.diagram.type === 'mermaid-streaming'
						? mount(MermaidStreaming, {
								target: placeholder,
								props: { source: segment.diagram.source }
							})
						: mount(MermaidDiagram, {
								target: placeholder,
								props: { source: segment.diagram.source }
							});

			mountedDiagrams.push({ component, placeholderId: segment.placeholderId });
		}

		if (mountVersion === wrappedDiagramMountVersion) {
			mountedWrappedDiagramSignature = wrappedDiagramSignature;
		}
	};

	afterUpdate(() => {
		mountInlineWebSources();
		mountWrappedDiagrams();
	});

	onDestroy(() => {
		wrappedDiagramMountVersion += 1;
		mountedWrappedDiagramSignature = '';
		destroyInlineWebSources();
		void destroyMountedDiagrams();
	});
</script>

<div class="markdown max-w-full" bind:this={container}>
	{#each segments as segment, index (index)}
		{#if segment.type === 'html'}
			<Sanitize html={segment.content} />
		{:else if segment.type === 'wrapped-diagram'}
			<Sanitize html={segment.content} />
		{:else if segment.type === 'mermaid-complete'}
			<MermaidDiagram source={segment.source} />
		{:else if segment.type === 'svg-complete' || segment.type === 'svg-streaming'}
			<SvgDiagram source={segment.source} isClosed={segment.type === 'svg-complete'} />
		{:else if segment.type === 'mermaid-streaming'}
			<MermaidStreaming source={segment.source} />
		{/if}
	{/each}
</div>
