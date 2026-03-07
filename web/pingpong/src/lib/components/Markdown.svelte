<script lang="ts">
	import { afterUpdate, onDestroy, tick } from 'svelte';
	import type { InlineWebSource } from '$lib/content';
	import { parseMarkdownSegments } from '$lib/markdown-segments';
	import MermaidDiagram from './MermaidDiagram.svelte';
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
	$: segments = parseMarkdownSegments(content, { syntax, latex });

	const destroyInlineWebSources = () => {
		mountedChips.forEach((chip) => chip.$destroy());
		mountedChips = [];
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

	afterUpdate(() => {
		mountInlineWebSources();
	});

	onDestroy(() => {
		destroyInlineWebSources();
	});
</script>

<div class="markdown max-w-full" bind:this={container}>
	{#each segments as segment, index (`${segment.type}-${index}`)}
		{#if segment.type === 'html'}
			<Sanitize html={segment.content} />
		{:else if segment.type === 'mermaid-complete'}
			<MermaidDiagram source={segment.source} />
		{:else if segment.type === 'svg-complete'}
			<SvgDiagram source={segment.source} isClosed={true} />
		{:else if segment.type === 'mermaid-streaming'}
			<div
				class="mermaid-block not-prose relative mb-4 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm"
			>
				<div
					class="flex items-center justify-between gap-3 border-b border-gray-200 bg-linear-to-r from-gray-50 to-white px-3 py-2"
				>
					<div class="text-xs font-semibold tracking-[0.18em] text-gray-500 uppercase">Mermaid</div>
					<div class="text-xs font-medium text-gray-500">Streaming code...</div>
				</div>
				<pre
					class="overflow-x-auto bg-gray-950 p-4 text-xs leading-6 whitespace-pre-wrap text-gray-100"><code
						>{segment.source}</code
					></pre>
			</div>
		{:else if segment.type === 'svg-streaming'}
			<SvgDiagram source={segment.source} isClosed={false} />
		{/if}
	{/each}
</div>
