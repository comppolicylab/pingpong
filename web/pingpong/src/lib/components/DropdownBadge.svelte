<script lang="ts">
	import { Badge } from 'flowbite-svelte';
	import type { Snippet } from 'svelte';
	interface Props {
		extraClasses?: string;
		icon?: Snippet;
		name?: Snippet;
	}

	let {
		extraClasses = 'border-amber-400 from-amber-50 to-amber-100 text-amber-700',
		icon,
		name
	}: Props = $props();
</script>

<Badge
	class="flex flex-row items-center gap-x-1 border bg-gradient-to-b px-2 py-0.5 text-xs
           normal-case shadow-xs {extraClasses}">{@render icon?.()}{@render name?.()}</Badge
>
