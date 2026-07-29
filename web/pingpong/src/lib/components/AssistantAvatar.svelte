<script lang="ts">
	import * as api from '$lib/api';
	import Logo from '$lib/components/Logo.svelte';

	const sizeClasses = {
		4: 'h-4 w-4',
		5: 'h-5 w-5',
		8: 'h-8 w-8',
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
	<Logo {size} extraClass="shrink-0 fill-amber-600 {extraClass}" />
{/if}

<style>
	.assistant-avatar-image {
		clip-path: circle(calc(50% - 0.5px) at center);
	}
</style>
