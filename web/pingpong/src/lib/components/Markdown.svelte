<script lang="ts">
	import { afterUpdate, onDestroy, tick } from 'svelte';
	import { markdown } from '$lib/markdown';
	import type { InlineWebSource } from '$lib/content';
	import Sanitize from './Sanitize.svelte';
	import WebSourceChip from './WebSourceChip.svelte';
	import 'katex/dist/katex.min.css';

	export let content = '';
	export let syntax = true;
	export let latex = false;
	export let inlineWebSources: InlineWebSource[] = [];

	let container: HTMLDivElement;
	let mountedChips: WebSourceChip[] = [];

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
	<Sanitize html={markdown(content, { syntax, latex })} />
</div>
