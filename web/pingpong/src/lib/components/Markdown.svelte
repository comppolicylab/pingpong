<script lang="ts">
	import { dev } from '$app/environment';
	import { afterUpdate, mount, onDestroy, tick, unmount } from 'svelte';
	import type { InlineWebSource } from '$lib/content';
	import { parseMarkdownSegments, type MarkdownSegment } from '$lib/markdown-segments';
	import Diagram from './Diagram.svelte';
	import Sanitize from './Sanitize.svelte';
	import WebSourceChip from './WebSourceChip.svelte';
	import 'katex/dist/katex.min.css';

	export let content = '';
	export let syntax = true;
	export let latex = false;
	export let inlineWebSources: InlineWebSource[] = [];

	let container: HTMLDivElement;
	let mountedChips: WebSourceChip[] = [];
	let mountedDiagrams: object[] = [];
	let wrappedDiagramMountVersion = 0;
	let loggedDiagramSignature = '';

	$: segments = parseMarkdownSegments(content, { syntax, latex });
	$: wrappedDiagramSegments = segments.filter(
		(
			segment
		): segment is Extract<
			MarkdownSegment,
			{ type: 'diagram'; wrapperHtml: string; placeholderId: string }
		> => segment.type === 'diagram' && 'wrapperHtml' in segment
	);
	$: wrappedDiagramSignature = JSON.stringify(
		wrappedDiagramSegments.map((segment) => ({
			placeholderId: segment.placeholderId,
			kind: segment.diagram.kind,
			state: segment.diagram.state,
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
		await Promise.all(mounted.map((component) => unmount(component)));
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

			mountedDiagrams.push(
				mount(Diagram, {
					target: placeholder,
					props: {
						kind: segment.diagram.kind,
						state: segment.diagram.state,
						source: segment.diagram.source
					}
				})
			);
		}

		if (mountVersion === wrappedDiagramMountVersion) {
			mountedWrappedDiagramSignature = wrappedDiagramSignature;
		}
	};

	afterUpdate(() => {
		mountInlineWebSources();
		mountWrappedDiagrams();
	});

	$: if (dev) {
		const diagramSegments = segments
			.filter((segment): segment is Extract<MarkdownSegment, { type: 'diagram' }> => {
				return segment.type === 'diagram';
			})
			.map((segment) => ({
				kind: segment.diagram.kind,
				state: segment.diagram.state,
				sourceLength: segment.diagram.source.length,
				wrapped: 'wrapperHtml' in segment
			}));
		const diagramSignature = JSON.stringify(diagramSegments);
		if (diagramSegments.length && diagramSignature !== loggedDiagramSignature) {
			loggedDiagramSignature = diagramSignature;
		}
	}

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
		{:else if 'wrapperHtml' in segment}
			<Sanitize html={segment.wrapperHtml} />
		{:else}
			<Diagram
				kind={segment.diagram.kind}
				state={segment.diagram.state}
				source={segment.diagram.source}
			/>
		{/if}
	{/each}
</div>
