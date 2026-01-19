<script lang="ts">
	import { Badge } from 'flowbite-svelte';
	export let extraClasses = 'border-amber-400 from-amber-50 to-amber-100 text-amber-700';
</script>

<Badge
	class="flex flex-row items-center gap-x-1 border bg-gradient-to-b px-2 py-0.5 text-xs
           normal-case shadow-xs {extraClasses}"><slot name="icon" /><slot name="name" /></Badge
>
