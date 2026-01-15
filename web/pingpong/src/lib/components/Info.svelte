<script lang="ts">
	import { P } from 'flowbite-svelte';
	interface Props {
		children?: import('svelte').Snippet;
	}

	let { children }: Props = $props();
</script>

<P weight="light" color="mt-2 text-gray-500 dark:text-gray-400">
	{@render children?.()}
</P>
