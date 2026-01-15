<script lang="ts" module>
	export const mainTextClass = 'text-3xl text-color-blue-dark-50 font-serif font-bold px-4';
</script>

<script lang="ts">
	interface Props {
		left?: import('svelte').Snippet;
		right?: import('svelte').Snippet;
	}

	let { left, right }: Props = $props();
</script>

<header
	class="items-center justify-between bg-blue-light-50 p-2 pt-6 pb-6 sm:flex sm:pb-2 lg:p-8 lg:pt-10 lg:pb-4"
>
	<div class="grow">
		{@render left?.()}
	</div>
	<div class="mt-4 ml-2 sm:mt-0 sm:ml-0">
		{@render right?.()}
	</div>
</header>
