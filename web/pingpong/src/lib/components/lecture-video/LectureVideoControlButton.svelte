<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		label,
		onclick,
		locked = false,
		active = false,
		pressed = undefined,
		children
	}: {
		label: string;
		onclick: () => void;
		locked?: boolean;
		active?: boolean;
		pressed?: boolean;
		children: Snippet;
	} = $props();

	function handleClick(event: MouseEvent) {
		event.stopPropagation();
		onclick();
	}
</script>

<div
	class="shrink-0 rounded-full bg-black/30 p-1 {locked
		? 'pointer-events-none invisible'
		: 'pointer-events-auto'}"
>
	<button
		class="flex h-8 w-8 items-center justify-center rounded-full text-white hover:bg-white/10 {active
			? 'bg-white/15'
			: ''}"
		style="transition: background-color 0.2s;"
		onclick={handleClick}
		aria-label={label}
		aria-pressed={pressed}
	>
		{@render children()}
	</button>
</div>
