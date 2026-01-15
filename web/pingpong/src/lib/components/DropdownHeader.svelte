<script lang="ts">
	import { DropdownItem } from 'flowbite-svelte';

	interface Props {
		// The name of the header.
		name: string;
		// The z-index order of the header. Increase this value to make the header appear on top of other elements.
		order?: number;
		// The color classes to apply to the header. Include a from and to class for the gradient.
		colorClasses?: string;
		// If true, the header will have a gradient background that extends above the dropdown.
		topHeader?: boolean;
		children?: import('svelte').Snippet;
	}

	let {
		name,
		order = 1,
		colorClasses = 'from-orange-dark to-orange',
		topHeader = false,
		children
	}: Props = $props();
</script>

<div
	class="sticky {name} top-0 z-{(order + 2) * 10} bg-gradient-to-r {colorClasses} drop-shadow-md"
>
	{#if topHeader}
		<div class="absolute inset-x-0 -top-96 h-96 bg-gradient-to-r {colorClasses}"></div>
	{/if}
	<DropdownItem disabled defaultClass="font-normal py-2 px-4 text-sm text-white"
		>{@render children?.()}</DropdownItem
	>
</div>
