<script lang="ts">
	import * as api from '$lib/api';
	import logo from './logo.svg?raw';

	const sizeClasses = {
		4: 'h-4 w-4',
		5: 'h-5 w-5',
		8: 'h-8 w-8',
		10: 'h-10 w-10',
		12: 'h-12 w-12',
		20: 'h-20 w-20'
	} as const;

	export let assistant: Pick<api.Assistant, 'avatar_url' | 'name'> | null = null;
	export let src = '';
	export let size: keyof typeof sizeClasses = 8;
	export let extraClass = '';
	export let showFallback = false;

	$: imageSrc = assistant?.avatar_url ? api.assistantAvatarUrl(assistant) : src;
	$: alt = `${assistant?.name || 'Assistant'} avatar`;
	$: sizeClass = sizeClasses[size];
</script>

{#if imageSrc}
	<img
		src={imageSrc}
		{alt}
		draggable={false}
		class="assistant-avatar-image {sizeClass} shrink-0 object-cover {extraClass}"
	/>
{:else if showFallback}
	<!-- The logo is taller than it is wide, so it is fitted inside a box of the
	     same footprint as a real avatar to keep rows aligned either way. -->
	<div
		class="assistant-avatar-fallback {sizeClass} flex shrink-0 items-center justify-center fill-amber-600 {extraClass}"
	>
		<!-- eslint-disable-next-line svelte/no-at-html-tags -->
		{@html logo}
	</div>
{/if}

<style>
	.assistant-avatar-image {
		clip-path: circle(calc(50% - 0.5px) at center);
	}

	.assistant-avatar-fallback :global(svg) {
		height: 100%;
		width: auto;
	}
</style>
