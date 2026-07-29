<script lang="ts">
	import * as api from '$lib/api';
	import Logo from '$lib/components/Logo.svelte';

	export let assistant: Pick<api.Assistant, 'avatar_url' | 'name'> | null = null;
	export let src = '';
	export let size = 8;
	export let extraClass = '';
	export let showFallback = false;

	$: imageSrc = assistant?.avatar_url ? api.assistantAvatarUrl(assistant) : src;
	$: alt = `${assistant?.name || 'Assistant'} avatar`;
</script>

{#if imageSrc}
	<img
		src={imageSrc}
		{alt}
		draggable={false}
		class="assistant-avatar-image h-{size} w-{size} shrink-0 object-cover {extraClass}"
	/>
{:else if showFallback}
	<Logo {size} extraClass="shrink-0 fill-amber-600 {extraClass}" />
{/if}

<style>
	.assistant-avatar-image {
		clip-path: circle(calc(50% - 0.5px) at center);
	}
</style>
