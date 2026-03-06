<script lang="ts">
	import { afterUpdate, onDestroy, tick } from 'svelte';
	import { mount, unmount } from 'svelte';
	import { markdown } from '$lib/markdown';
	import type { InlineWebSource } from '$lib/content';
	import MermaidDiagram from './MermaidDiagram.svelte';
	import Sanitize from './Sanitize.svelte';
	import WebSourceChip from './WebSourceChip.svelte';
	import 'katex/dist/katex.min.css';

	export let content = '';
	export let syntax = true;
	export let latex = false;
	export let inlineWebSources: InlineWebSource[] = [];

	type MountedMermaidComponent = ReturnType<typeof mount>;

	let container: HTMLDivElement;
	let mountedChips: WebSourceChip[] = [];
	let mountedMermaidDiagrams: { target: HTMLElement; component: MountedMermaidComponent }[] = [];

	const destroyInlineWebSources = () => {
		mountedChips.forEach((chip) => chip.$destroy());
		mountedChips = [];
	};

	const destroyMermaidDiagrams = () => {
		mountedMermaidDiagrams.forEach(({ component }) => {
			void unmount(component);
		});
		mountedMermaidDiagrams = [];
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

	const mountMermaidDiagrams = async () => {
		if (!container) {
			return;
		}

		mountedMermaidDiagrams = mountedMermaidDiagrams.filter(({ target, component }) => {
			const stillMounted = target.isConnected && container.contains(target);
			if (!stillMounted) {
				void unmount(component);
			}
			return stillMounted;
		});

		const mermaidBlocks = [
			...container.querySelectorAll<HTMLElement>('pre > code.language-mermaid')
		];
		mermaidBlocks.forEach((block) => {
			const pre = block.parentElement;
			const source = block.textContent?.trim();
			if (!pre || !source) {
				return;
			}

			const target = document.createElement('div');
			target.className = 'mb-4 overflow-hidden';
			pre.replaceWith(target);

			const component = mount(MermaidDiagram, {
				target,
				props: { source }
			}) as MountedMermaidComponent;

			mountedMermaidDiagrams.push({ target, component });
		});
	};

	afterUpdate(() => {
		mountInlineWebSources();
		mountMermaidDiagrams();
	});

	onDestroy(() => {
		destroyInlineWebSources();
		destroyMermaidDiagrams();
	});
</script>

<div class="markdown max-w-full" bind:this={container}>
	<Sanitize html={markdown(content, { syntax, latex })} />
</div>
