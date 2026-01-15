<script lang="ts">
	import { onDestroy, tick, mount, unmount } from 'svelte';
	import { markdown } from '$lib/markdown';
	import type { InlineWebSource } from '$lib/content';
	import Sanitize from './Sanitize.svelte';
	import WebSourceChip from './WebSourceChip.svelte';
	import 'katex/dist/katex.min.css';

	interface Props {
		content: string;
		syntax?: boolean;
		latex?: boolean;
		inlineWebSources?: InlineWebSource[];
	}

	let { content, syntax = true, latex = false, inlineWebSources = [] }: Props = $props();

	let container: HTMLDivElement;
	let mountedChips: WebSourceChip[] = [];

	const destroyInlineWebSources = () => {
		mountedChips.forEach((chip) => unmount(chip));
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
				mount(WebSourceChip, {
					target: placeholder as HTMLElement,
					props: { source: source.source, type: 'chip' }
				})
			);
		});
	};

	$effect(() => {
		mountInlineWebSources();
	});

	onDestroy(() => {
		destroyInlineWebSources();
	});
</script>

<div class="markdown max-w-full" bind:this={container}>
	<Sanitize html={markdown(content, { syntax, latex })} />
</div>
