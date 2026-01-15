<script lang="ts">
	import { slide } from 'svelte/transition';
	import { BrainOutline, ChevronDownOutline } from 'flowbite-svelte-icons';
	import type { ReasoningCallItem } from '$lib/api';
	import Markdown from './Markdown.svelte';

	interface Props {
		content: ReasoningCallItem;
		forceOpen?: boolean;
	}

	let { content, forceOpen = false }: Props = $props();

	let open = $state(false);
	let previousOpen: boolean | null = $state(null);
	$effect(() => {
		if (forceOpen) {
			if (previousOpen === null) {
				previousOpen = open;
			}
			open = true;
		} else if (previousOpen !== null) {
			open = previousOpen;
			previousOpen = null;
		}
	});

	let hasSummary = $derived((content.summary && content.summary.length > 0) || false);

	const toggle = () => {
		if (hasSummary) {
			open = !open;
		}
	};

	let statusLabel =
		$derived(content.status === 'completed'
			? 'Thought' +
				(content.thought_for ? ' for ' + content.thought_for : ' before responding') +
				(open ? '...' : '')
			: content.status === 'incomplete'
				? 'Reasoning was interrupted'
				: 'Thinking...');

	let statusClasses =
		$derived(content.status === 'in_progress'
			? 'text-sm font-medium shimmer'
			: content.status === 'incomplete'
				? 'text-sm font-medium text-yellow-600'
				: 'text-sm font-medium text-gray-600');
</script>

<div class="my-3">
	<div class="flex items-center gap-2">
		<BrainOutline class="h-4 w-4 text-gray-600" />
		<button
			type="button"
			class="flex flex-row items-center gap-1 disabled:cursor-default"
			onclick={toggle}
			disabled={!hasSummary}
		>
			<span class={statusClasses}>
				{statusLabel}
			</span>
			{#if hasSummary}
				{#if open}
					<ChevronDownOutline class="rotate-180 transform text-gray-600" />
				{:else}
					<ChevronDownOutline class="text-gray-600" />
				{/if}
			{/if}
		</button>
	</div>
	{#if open && hasSummary}
		<div
			class="mt-2 ml-2 border-l border-gray-200 pl-4 text-sm font-light text-gray-600"
			transition:slide={{ duration: 250 }}
		>
			{#each content.summary as part, i (part.id ?? `${part.part_index}-${i}`)}
				<div class="py-0.5 leading-5" transition:slide={{ delay: i * 80, duration: 250 }}>
					<Markdown content={part.summary_text.trim()} latex={true} />
				</div>
			{/each}
		</div>
	{/if}
</div>

<style lang="css">
	.shimmer {
		color: transparent;
		-webkit-text-fill-color: transparent;
		animation-delay: 0s;
		animation-duration: 2s;
		animation-iteration-count: infinite;
		animation-name: shimmer;
		background: #4b5563 -webkit-gradient(
				linear,
				100% 0,
				0 0,
				from(#5d5d5d),
				color-stop(0.4, #ffffffbf),
				to(#4b5563),
				color-stop(0.6, #ffffffbf),
				to(#4b5563)
			);
		-webkit-background-clip: text;
		background-clip: text;
		background-position: -100% 0;
		background-position: unset top;
		background-repeat: no-repeat;
		background-size: 50% 200%;
	}

	@keyframes shimmer {
		0% {
			background-position: -100% 0;
		}
		100% {
			background-position: 250% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.shimmer {
			animation: none;
		}
	}

	.shimmer:hover {
		-webkit-text-fill-color: #374151;
		color: #374151;
		background: 0 0;
	}
</style>
